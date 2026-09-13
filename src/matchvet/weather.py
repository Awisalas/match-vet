"""T08 Open-Meteo weather evidence for eligible Target Matches.

Weather is an Important Evidence input by default.  This module never treats a
missing venue or forecast as ordinary weather and never lets a post-cutoff run
enter frozen evidence.  Network retrieval is kept behind a small client seam so
recorded JSON fixtures can exercise the same parser offline.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from matchvet.evidence import CutoffEligibility, EvidenceClass, EvidenceState
from matchvet.store import CanonicalIdentifier, Store


class WeatherError(Exception):
    """Base class for T08 weather failures."""


class WeatherUnavailable(WeatherError):
    """Open-Meteo could not be reached or its response was unavailable."""


class WeatherPolicyError(WeatherError):
    """A weather request would leave the approved source or resource policy."""


class WeatherParseError(WeatherError, ValueError):
    """An Open-Meteo response cannot be trusted as a forecast."""


class Freshness(StrEnum):
    CUTOFF_VALID = "CUTOFF_VALID"
    POST_CUTOFF = "POST_CUTOFF"
    UNKNOWN = "UNKNOWN"


OBSERVED = EvidenceState.OBSERVED
UNKNOWN = EvidenceState.UNKNOWN
WEATHER_ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_SOURCE_KEY = "open-meteo"
OPEN_METEO_TERMS = "https://creativecommons.org/licenses/by/4.0/"
DEFAULT_WEATHER_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
)


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WeatherParseError(
            "Weather timestamps must be ISO-8601 values with an explicit UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise WeatherParseError("Weather timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherParseError(f"Open-Meteo {label} must contain numeric values.")
    return float(value)


@dataclass(frozen=True)
class VenueLocation:
    """Verified venue coordinates plus their location provenance."""

    venue_id: str
    venue_name: str
    latitude: float | None
    longitude: float | None
    source_key: str
    locator: str
    observed_at_utc: str
    source_capture_id: str | None = None

    def __post_init__(self) -> None:
        if not self.venue_id.strip() or not self.venue_name.strip():
            raise WeatherParseError("Venue location requires an ID and name.")
        if not self.source_key.strip() or not self.locator.strip():
            raise WeatherParseError("Venue location requires source provenance.")
        object.__setattr__(self, "observed_at_utc", _canonical_utc(self.observed_at_utc))
        if (self.latitude is None) != (self.longitude is None):
            raise WeatherParseError("Venue location coordinates must be present together.")
        if (
            self.latitude is not None
            and self.longitude is not None
            and (not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180)
        ):
            raise WeatherParseError("Venue location coordinates are outside valid ranges.")

    @property
    def available(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def provenance(self) -> Mapping[str, str | None]:
        return MappingProxyType(
            {
                "locator": self.locator,
                "observed_at_utc": self.observed_at_utc,
                "source_capture_id": self.source_capture_id,
                "source_key": self.source_key,
                "venue_id": self.venue_id,
                "venue_name": self.venue_name,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "locator": self.locator,
            "observed_at_utc": self.observed_at_utc,
            "source_capture_id": self.source_capture_id,
            "source_key": self.source_key,
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
        }


@dataclass(frozen=True)
class WeatherRequest:
    fixture_id: str
    target_time_utc: str
    cutoff_utc: str
    location: VenueLocation
    model: str = "best_match"
    variables: tuple[str, ...] = DEFAULT_WEATHER_VARIABLES
    target_interval_hours: int = 1

    def __post_init__(self) -> None:
        if not self.fixture_id.strip():
            raise WeatherParseError("Weather requests require a Target Match ID.")
        if not self.location.available:
            raise WeatherParseError("Weather requests require verified venue coordinates.")
        object.__setattr__(self, "target_time_utc", _canonical_utc(self.target_time_utc))
        object.__setattr__(self, "cutoff_utc", _canonical_utc(self.cutoff_utc))
        if not self.model.strip():
            raise WeatherParseError("Open-Meteo model is required.")
        variables = tuple(dict.fromkeys(item.strip() for item in self.variables if item.strip()))
        if not variables:
            raise WeatherParseError("At least one Open-Meteo hourly variable is required.")
        object.__setattr__(self, "variables", variables)
        if self.target_interval_hours <= 0:
            raise WeatherParseError("Weather target interval must be positive.")

    @property
    def target_time(self) -> datetime:
        return _parse_utc(self.target_time_utc)

    @property
    def cutoff(self) -> datetime:
        return _parse_utc(self.cutoff_utc)

    @property
    def interval_start_utc(self) -> str:
        return self.target_time.replace(minute=0, second=0, microsecond=0).isoformat(
            timespec="microseconds"
        )

    @property
    def interval_end_utc(self) -> str:
        return (
            _parse_utc(self.interval_start_utc) + timedelta(hours=self.target_interval_hours)
        ).isoformat(timespec="microseconds")

    @property
    def url(self) -> str:
        selected_date = self.target_time.date().isoformat()
        params = (
            ("latitude", f"{self.location.latitude:.5f}"),
            ("longitude", f"{self.location.longitude:.5f}"),
            ("hourly", ",".join(self.variables)),
            ("models", self.model),
            ("start_date", selected_date),
            ("end_date", selected_date),
            ("timezone", "UTC"),
        )
        return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"

    @property
    def cache_key(self) -> str:
        return _digest(
            {
                "cutoff_utc": self.cutoff_utc,
                "location": {
                    "latitude": self.location.latitude,
                    "longitude": self.location.longitude,
                },
                "model": self.model,
                "target_interval_hours": self.target_interval_hours,
                "target_time_utc": self.target_time_utc,
                "variables": self.variables,
            }
        )


@dataclass(frozen=True)
class WeatherHTTPResponse:
    content: bytes
    retrieved_at_utc: str
    response_status: int = 200
    content_type: str = "application/json"
    from_cache: bool = False
    bytes_downloaded: int = 0
    url: str | None = None

    def __post_init__(self) -> None:
        if self.response_status < 100 or self.response_status > 599:
            raise WeatherUnavailable("Open-Meteo response status is invalid.")
        object.__setattr__(self, "retrieved_at_utc", _canonical_utc(self.retrieved_at_utc))


class WeatherClient(Protocol):
    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse: ...


@dataclass(frozen=True)
class WeatherEvidence:
    fixture_id: str
    target_time_utc: str
    cutoff_utc: str
    state: EvidenceState
    evidence_class: EvidenceClass = EvidenceClass.IMPORTANT
    cutoff_eligibility: CutoffEligibility = CutoffEligibility.INDETERMINATE
    freshness: Freshness = Freshness.UNKNOWN
    unknown_reason: str | None = None
    forecast_model: str | None = None
    forecast_issue_time_utc: str | None = None
    forecast_issue_time_source: str | None = None
    retrieved_at_utc: str | None = None
    forecast_target_time_utc: str | None = None
    forecast_interval_start_utc: str | None = None
    forecast_interval_end_utc: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    values: Mapping[str, float] = field(default_factory=dict)
    units: Mapping[str, str] = field(default_factory=dict)
    location_provenance: Mapping[str, str | None] = field(default_factory=dict)
    attribution: str = WEATHER_ATTRIBUTION
    source_locator: str | None = OPEN_METEO_FORECAST_URL
    response_status: int | None = None
    response_content_sha256: str | None = None
    response_bytes: bytes | None = field(default=None, repr=False, compare=False)
    eligible_target_match: bool = True
    freshness_age_seconds_at_cutoff: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_time_utc", _canonical_utc(self.target_time_utc))
        object.__setattr__(self, "cutoff_utc", _canonical_utc(self.cutoff_utc))
        if self.evidence_class is not EvidenceClass.IMPORTANT:
            raise WeatherParseError("T08 weather evidence is Important by default.")
        if self.state is EvidenceState.OBSERVED:
            if not self.forecast_model or not self.forecast_issue_time_utc:
                raise WeatherParseError("Observed weather requires model and issue time.")
            if self.unknown_reason is not None:
                raise WeatherParseError("Observed weather cannot have an UNKNOWN reason.")
        elif not self.unknown_reason:
            raise WeatherParseError("UNKNOWN weather requires a reason.")
        if self.forecast_issue_time_utc is not None:
            object.__setattr__(
                self, "forecast_issue_time_utc", _canonical_utc(self.forecast_issue_time_utc)
            )
        if self.retrieved_at_utc is not None:
            object.__setattr__(self, "retrieved_at_utc", _canonical_utc(self.retrieved_at_utc))
        for name in (
            "forecast_target_time_utc",
            "forecast_interval_start_utc",
            "forecast_interval_end_utc",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _canonical_utc(value))
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "units", MappingProxyType(dict(self.units)))
        object.__setattr__(
            self, "location_provenance", MappingProxyType(dict(self.location_provenance))
        )
        if self.response_bytes is not None and self.response_content_sha256 is None:
            object.__setattr__(
                self,
                "response_content_sha256",
                hashlib.sha256(self.response_bytes).hexdigest(),
            )

    @property
    def is_frozen_input(self) -> bool:
        return (
            self.eligible_target_match
            and self.state is EvidenceState.OBSERVED
            and self.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "attribution": self.attribution,
            "cutoff_eligibility": self.cutoff_eligibility.value,
            "cutoff_utc": self.cutoff_utc,
            "eligible_target_match": self.eligible_target_match,
            "evidence_class": self.evidence_class.value,
            "forecast_interval_end_utc": self.forecast_interval_end_utc,
            "forecast_interval_start_utc": self.forecast_interval_start_utc,
            "forecast_issue_time_source": self.forecast_issue_time_source,
            "forecast_issue_time_utc": self.forecast_issue_time_utc,
            "forecast_model": self.forecast_model,
            "forecast_target_time_utc": self.forecast_target_time_utc,
            "freshness": self.freshness.value,
            "freshness_age_seconds_at_cutoff": self.freshness_age_seconds_at_cutoff,
            "latitude": self.latitude,
            "location_provenance": dict(self.location_provenance),
            "longitude": self.longitude,
            "response_content_sha256": self.response_content_sha256,
            "response_status": self.response_status,
            "retrieved_at_utc": self.retrieved_at_utc,
            "source_locator": self.source_locator,
            "state": self.state.value,
            "target_time_utc": self.target_time_utc,
            "units": dict(self.units),
            "unknown_reason": self.unknown_reason,
            "values": dict(self.values),
        }


def _issue_time(payload: Mapping[str, object], retrieved_at_utc: str) -> tuple[str, str]:
    for key in ("forecast_issue_time", "issue_time", "issued_at", "run_time", "update_time"):
        value = payload.get(key)
        if isinstance(value, str):
            return _canonical_utc(value), key
    # Open-Meteo does not expose a run timestamp on every endpoint response.  The
    # retrieval instant is the conservative auditable bound for that response.
    return _canonical_utc(retrieved_at_utc), "retrieval_time_bound"


def _payload_mapping(
    payload: bytes | Mapping[str, object],
) -> tuple[Mapping[str, object], bytes | None]:
    if isinstance(payload, bytes):
        try:
            loaded: object = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WeatherParseError("Open-Meteo response is not valid JSON.") from error
        if not isinstance(loaded, dict):
            raise WeatherParseError("Open-Meteo response must be a JSON object.")
        return loaded, payload
    if not isinstance(payload, Mapping):
        raise WeatherParseError("Open-Meteo response must be a JSON object.")
    return payload, None


def _unknown(
    *,
    fixture_id: str,
    target_time_utc: str,
    cutoff_utc: str,
    reason: str,
    location: VenueLocation | None = None,
    eligible_target_match: bool = True,
    cutoff_eligibility: CutoffEligibility = CutoffEligibility.INDETERMINATE,
    freshness: Freshness = Freshness.UNKNOWN,
    retrieved_at_utc: str | None = None,
    response: WeatherHTTPResponse | None = None,
    source_locator: str | None = OPEN_METEO_FORECAST_URL,
) -> WeatherEvidence:
    return WeatherEvidence(
        fixture_id=fixture_id,
        target_time_utc=target_time_utc,
        cutoff_utc=cutoff_utc,
        state=EvidenceState.UNKNOWN,
        cutoff_eligibility=cutoff_eligibility,
        freshness=freshness,
        unknown_reason=reason,
        retrieved_at_utc=retrieved_at_utc or (response.retrieved_at_utc if response else None),
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        location_provenance=location.provenance if location else {},
        source_locator=source_locator,
        response_status=response.response_status if response else None,
        response_content_sha256=(
            hashlib.sha256(response.content).hexdigest() if response is not None else None
        ),
        response_bytes=response.content if response is not None else None,
        eligible_target_match=eligible_target_match,
    )


def parse_open_meteo_response(
    payload: bytes | Mapping[str, object],
    request: WeatherRequest,
    *,
    retrieved_at_utc: str,
    response_status: int = 200,
    source_locator: str | None = None,
) -> WeatherEvidence:
    """Parse and cutoff-classify one Open-Meteo response."""

    if response_status != 200:
        raise WeatherParseError(f"Open-Meteo response status is {response_status}.")
    response, raw = _payload_mapping(payload)
    latitude = _number(response.get("latitude"), "latitude")
    longitude = _number(response.get("longitude"), "longitude")
    assert request.location.latitude is not None and request.location.longitude is not None
    if (
        abs(latitude - request.location.latitude) > 0.1
        or abs(longitude - request.location.longitude) > 0.1
    ):
        raise WeatherParseError("Open-Meteo response coordinates do not match the requested venue.")
    hourly = response.get("hourly")
    if not isinstance(hourly, Mapping):
        raise WeatherParseError("Open-Meteo response has no hourly forecast object.")
    times = hourly.get("time")
    if not isinstance(times, list) or not times or not all(isinstance(item, str) for item in times):
        raise WeatherParseError("Open-Meteo hourly forecast has no valid time array.")
    parsed_times: list[datetime] = []
    for value in times:
        raw_time = value.replace("Z", "+00:00")
        if "+" not in raw_time and "-" not in raw_time[10:]:
            raw_time += "+00:00"
        try:
            parsed_time = datetime.fromisoformat(raw_time)
        except ValueError as error:
            raise WeatherParseError("Open-Meteo hourly time is malformed.") from error
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=UTC)
        parsed_times.append(parsed_time.astimezone(UTC))
    target = request.target_time
    selected_index: int | None = None
    for index, point in enumerate(parsed_times):
        if point <= target < point + timedelta(hours=request.target_interval_hours):
            selected_index = index
            break
    if selected_index is None:
        raise WeatherParseError("Open-Meteo forecast does not cover the target interval.")
    values: dict[str, float] = {}
    for variable in request.variables:
        series = hourly.get(variable)
        if not isinstance(series, list) or selected_index >= len(series):
            continue
        values[variable] = _number(series[selected_index], f"{variable} forecast")
    if not values:
        raise WeatherParseError("Open-Meteo response has no usable requested hourly values.")
    units_raw = response.get("hourly_units")
    units = (
        {key: str(value) for key, value in units_raw.items() if key in values}
        if isinstance(units_raw, Mapping)
        else {}
    )
    issue_time, issue_source = _issue_time(response, retrieved_at_utc)
    issue = _parse_utc(issue_time)
    cutoff = request.cutoff
    retrieved = _parse_utc(retrieved_at_utc)
    cutoff_valid = issue <= cutoff and retrieved <= cutoff
    eligibility = CutoffEligibility.CUTOFF_VALID if cutoff_valid else CutoffEligibility.POST_CUTOFF
    freshness = Freshness.CUTOFF_VALID if cutoff_valid else Freshness.POST_CUTOFF
    age = max(0.0, (cutoff - issue).total_seconds())
    return WeatherEvidence(
        fixture_id=request.fixture_id,
        target_time_utc=request.target_time_utc,
        cutoff_utc=request.cutoff_utc,
        state=(
            EvidenceState.OBSERVED
            if eligibility is CutoffEligibility.CUTOFF_VALID
            else EvidenceState.UNKNOWN
        ),
        cutoff_eligibility=eligibility,
        freshness=freshness,
        unknown_reason=(None if cutoff_valid else "FORECAST_POST_CUTOFF"),
        forecast_model=str(response.get("model") or request.model),
        forecast_issue_time_utc=issue_time,
        forecast_issue_time_source=issue_source,
        retrieved_at_utc=_canonical_utc(retrieved_at_utc),
        forecast_target_time_utc=request.target_time_utc,
        forecast_interval_start_utc=parsed_times[selected_index].isoformat(timespec="microseconds"),
        forecast_interval_end_utc=(
            parsed_times[selected_index] + timedelta(hours=request.target_interval_hours)
        ).isoformat(timespec="microseconds"),
        latitude=latitude,
        longitude=longitude,
        values=values,
        units=units,
        location_provenance=request.location.provenance,
        source_locator=source_locator or request.url,
        response_status=response_status,
        response_content_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
        response_bytes=raw,
        freshness_age_seconds_at_cutoff=age,
    )


def _reason_for_parse_error(error: WeatherParseError) -> str:
    message = str(error).casefold()
    if "coordinates" in message:
        return "FORECAST_WRONG_VENUE"
    if "target interval" in message:
        return "FORECAST_OUTSIDE_TARGET_INTERVAL"
    if "json" in message or "object" in message or "hourly" in message:
        return "MALFORMED_RESPONSE"
    return "FORECAST_UNAVAILABLE"


def build_weather_evidence(
    *,
    fixture_id: str,
    target_time_utc: str,
    cutoff_utc: str,
    location: VenueLocation | None,
    client: WeatherClient | None,
    eligible_target_match: bool = True,
    refresh: bool = False,
) -> WeatherEvidence:
    """Fetch and parse weather for one eligible Target Match only."""

    if not eligible_target_match:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="NOT_ELIGIBLE_TARGET_MATCH",
            location=location,
            eligible_target_match=False,
        )
    if location is None or not location.available:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="VENUE_LOCATION_UNKNOWN",
            location=location,
        )
    if _parse_utc(location.observed_at_utc) > _parse_utc(cutoff_utc):
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="LOCATION_POST_CUTOFF",
            location=location,
            cutoff_eligibility=CutoffEligibility.POST_CUTOFF,
            freshness=Freshness.POST_CUTOFF,
        )
    if client is None:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="WEATHER_CLIENT_UNAVAILABLE",
            location=location,
        )
    request = WeatherRequest(
        fixture_id=fixture_id,
        target_time_utc=target_time_utc,
        cutoff_utc=cutoff_utc,
        location=location,
    )
    try:
        response = client.fetch(request, refresh=refresh)
    except WeatherError, HTTPError, URLError, OSError, TimeoutError:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="WEATHER_UNAVAILABLE",
            location=location,
            source_locator=request.url,
        )
    if response.response_status != 200:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason="WEATHER_UNAVAILABLE",
            location=location,
            response=response,
            source_locator=response.url or request.url,
        )
    try:
        return parse_open_meteo_response(
            response.content,
            request,
            retrieved_at_utc=response.retrieved_at_utc,
            response_status=response.response_status,
            source_locator=response.url or request.url,
        )
    except WeatherParseError as error:
        return _unknown(
            fixture_id=fixture_id,
            target_time_utc=target_time_utc,
            cutoff_utc=cutoff_utc,
            reason=_reason_for_parse_error(error),
            location=location,
            response=response,
            source_locator=response.url or request.url,
        )


class StaticWeatherClient:
    """Deterministic offline Open-Meteo adapter for recorded response fixtures."""

    def __init__(
        self,
        responses: Mapping[str, bytes | Mapping[str, object]],
        *,
        retrieved_at_utc: str = "2026-09-13T10:00:00+00:00",
    ) -> None:
        self.responses = dict(responses)
        self.retrieved_at_utc = _canonical_utc(retrieved_at_utc)
        self.calls: list[str] = []

    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
        del refresh
        self.calls.append(request.url)
        try:
            payload = self.responses[request.url]
        except KeyError as error:
            raise WeatherUnavailable(
                f"No recorded Open-Meteo response for {request.url}."
            ) from error
        content = payload if isinstance(payload, bytes) else _canonical_json(payload)
        return WeatherHTTPResponse(
            content=content,
            retrieved_at_utc=self.retrieved_at_utc,
            url=request.url,
        )


class OpenMeteoClient:
    """Bounded direct Open-Meteo client with a private content cache."""

    def __init__(
        self,
        private_root: Path,
        *,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        network_cap_bytes: int = 250 * 1024 * 1024,
        cache_ttl_seconds: int = 60 * 60,
    ) -> None:
        if min(max_response_bytes, network_cap_bytes, int(timeout_seconds), cache_ttl_seconds) <= 0:
            raise ValueError("Open-Meteo client limits must be positive.")
        self.private_root = private_root.resolve()
        self.cache_root = self.private_root / "cache" / "t08-weather"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cache_root, 0o700)
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.network_cap_bytes = network_cap_bytes
        self.cache_ttl_seconds = cache_ttl_seconds
        self.network_bytes = 0

    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
        self._validate_url(request.url)
        stem = hashlib.sha256(request.cache_key.encode("utf-8")).hexdigest()
        data_path = self.cache_root / f"{stem}.data"
        metadata_path = self.cache_root / f"{stem}.json"
        cached = self._read_cache(data_path, metadata_path, request.url, refresh)
        if cached is not None:
            return cached
        http_request = Request(
            request.url,
            headers={
                "Accept": "application/json",
                "User-Agent": "MatchVet-T08/1.0",
            },
            method="GET",
        )
        try:
            response = urlopen(http_request, timeout=self.timeout_seconds)
        except (HTTPError, URLError, OSError) as error:
            raise WeatherUnavailable(f"Open-Meteo retrieval failed: {error}") from error
        status = int(getattr(response, "status", response.getcode()))
        if status != 200:
            response.close()
            raise WeatherUnavailable(f"Open-Meteo returned HTTP {status}.")
        content = bytearray()
        try:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                if len(content) + len(chunk) > self.max_response_bytes:
                    raise WeatherUnavailable("Open-Meteo response exceeded its bounded size.")
                if self.network_bytes + len(content) + len(chunk) > self.network_cap_bytes:
                    raise WeatherUnavailable("Open-Meteo network budget was exceeded.")
                content.extend(chunk)
        finally:
            response.close()
        body = bytes(content)
        retrieved = datetime.now(UTC).isoformat(timespec="microseconds")
        data_path.write_bytes(body)
        os.chmod(data_path, 0o600)
        metadata_path.write_text(
            json.dumps(
                {
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "content_type": str(
                        response.headers.get("Content-Type", "application/json")
                    ).split(";", maxsplit=1)[0],
                    "retrieved_at_utc": retrieved,
                    "response_status": status,
                    "url": request.url,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.chmod(metadata_path, 0o600)
        self.network_bytes += len(body)
        return WeatherHTTPResponse(
            content=body,
            retrieved_at_utc=retrieved,
            response_status=status,
            content_type="application/json",
            bytes_downloaded=len(body),
            url=request.url,
        )

    def _validate_url(self, url: str) -> None:
        if not url.startswith("https://api.open-meteo.com/v1/forecast?"):
            raise WeatherPolicyError("T08 permits only the approved Open-Meteo forecast endpoint.")

    def _read_cache(
        self,
        data_path: Path,
        metadata_path: Path,
        url: str,
        refresh: bool,
    ) -> WeatherHTTPResponse | None:
        if refresh or not data_path.is_file() or not metadata_path.is_file():
            return None
        try:
            raw: object = json.loads(metadata_path.read_text(encoding="utf-8"))
            body = data_path.read_bytes()
            if not isinstance(raw, dict):
                return None
            retrieved = raw.get("retrieved_at_utc")
            digest = raw.get("content_sha256")
            if not isinstance(retrieved, str) or not isinstance(digest, str):
                return None
            age = (datetime.now(UTC) - _parse_utc(retrieved)).total_seconds()
            if age > self.cache_ttl_seconds or digest != hashlib.sha256(body).hexdigest():
                return None
            return WeatherHTTPResponse(
                content=body,
                retrieved_at_utc=retrieved,
                response_status=int(raw.get("response_status", 200)),
                content_type=str(raw.get("content_type", "application/json")),
                from_cache=True,
                url=url,
            )
        except OSError, ValueError, TypeError, json.JSONDecodeError:
            return None


@dataclass(frozen=True)
class WeatherTarget:
    fixture_id: str
    target_time_utc: str
    cutoff_utc: str
    location: VenueLocation | None
    eligible_target_match: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_time_utc", _canonical_utc(self.target_time_utc))
        object.__setattr__(self, "cutoff_utc", _canonical_utc(self.cutoff_utc))


TargetMatchWeatherInput = WeatherTarget


@dataclass(frozen=True)
class WeatherBatch:
    evidence: tuple[WeatherEvidence, ...]
    target_count: int
    network_calls: int

    @property
    def frozen_evidence(self) -> tuple[WeatherEvidence, ...]:
        return tuple(item for item in self.evidence if item.is_frozen_input)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "evidence": [item.to_dict() for item in self.evidence],
                "network_calls": self.network_calls,
                "target_count": self.target_count,
            }
        )


class WeatherEvidenceBuilder:
    """Build weather evidence for a finite Target Match list."""

    def __init__(self, client: WeatherClient | None) -> None:
        self.client = client

    def build(
        self,
        targets: Sequence[WeatherTarget],
        *,
        refresh: bool = False,
    ) -> WeatherBatch:
        before_calls = len(getattr(self.client, "calls", ())) if self.client is not None else 0
        evidence = tuple(
            build_weather_evidence(
                fixture_id=target.fixture_id,
                target_time_utc=target.target_time_utc,
                cutoff_utc=target.cutoff_utc,
                location=target.location,
                client=self.client,
                eligible_target_match=target.eligible_target_match,
                refresh=refresh,
            )
            for target in targets
        )
        after_calls = (
            len(getattr(self.client, "calls", ())) if self.client is not None else before_calls
        )
        return WeatherBatch(evidence, len(targets), after_calls - before_calls)


@dataclass(frozen=True)
class StoredWeatherEvidence:
    weather_evidence_id: str
    matchweek_id: str
    target_fixture_id: str
    evidence: WeatherEvidence
    location_id: str | None
    capture_id: str | None
    evidence_digest: str


class WeatherLocationRecorder:
    """Persist verified venue location provenance without silently changing coordinates."""

    def __init__(self, store: Store) -> None:
        if not isinstance(store, Store) or store.status.mode.value != "READ_WRITE":
            raise PermissionError("Weather location recording requires a healthy writable store.")
        self.store = store

    def record(
        self,
        location: VenueLocation,
        *,
        created_at_utc: str | None = None,
    ) -> str:
        from matchvet.ingestion import deterministic_identifier

        location_id = deterministic_identifier("weather_location", location.venue_id)
        created = (
            _canonical_utc(created_at_utc)
            if created_at_utc
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
        with self.store.transaction() as transaction:
            existing = transaction.execute(
                """
                SELECT location_id, venue_name, latitude, longitude, source_key, locator,
                       observed_at_utc, provenance_json
                FROM weather_locations WHERE venue_key = ?
                """,
                (location.venue_id,),
            ).fetchone()
            if existing is not None:
                existing_provenance = json.loads(str(existing[7]))
                if (
                    str(existing[1]) != location.venue_name
                    or existing[2] != location.latitude
                    or existing[3] != location.longitude
                    or str(existing[4]) != location.source_key
                    or str(existing[5]) != location.locator
                    or existing_provenance != dict(location.provenance)
                ):
                    raise WeatherError("Venue location identity was reused with different content.")
                return str(existing[0])
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("weather_location", location_id)
            )
            transaction.execute(
                """
                INSERT INTO weather_locations (
                    location_id, venue_key, venue_name, latitude, longitude, location_state,
                    source_key, locator, source_capture_id, observed_at_utc, provenance_json,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    location_id,
                    location.venue_id,
                    location.venue_name,
                    location.latitude,
                    location.longitude,
                    "OBSERVED" if location.available else "UNKNOWN",
                    location.source_key,
                    location.locator,
                    location.source_capture_id,
                    location.observed_at_utc,
                    _canonical_json(dict(location.provenance)).decode(),
                    created,
                ),
            )
        return location_id

    def get(self, venue_id: str) -> VenueLocation | None:
        row = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT venue_key, venue_name, latitude, longitude, source_key, locator,
                   observed_at_utc, source_capture_id
            FROM weather_locations WHERE venue_key = ?
            """,
                (venue_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return VenueLocation(
            venue_id=str(row[0]),
            venue_name=str(row[1]),
            latitude=float(row[2]) if row[2] is not None else None,
            longitude=float(row[3]) if row[3] is not None else None,
            source_key=str(row[4]),
            locator=str(row[5]),
            observed_at_utc=str(row[6]),
            source_capture_id=str(row[7]) if row[7] is not None else None,
        )


def _weather_request_key(evidence: WeatherEvidence) -> str:
    return _digest(
        {
            "fixture_id": evidence.fixture_id,
            "latitude": evidence.latitude,
            "longitude": evidence.longitude,
            "model": evidence.forecast_model,
            "target_time_utc": evidence.target_time_utc,
        }
    )


class WeatherEvidenceRecorder:
    """Publish immutable weather captures and Important evidence rows."""

    def __init__(self, store: Store) -> None:
        if not isinstance(store, Store) or store.status.mode.value != "READ_WRITE":
            raise PermissionError("Weather evidence recording requires a healthy writable store.")
        self.store = store
        self.locations = WeatherLocationRecorder(store)

    def record(
        self,
        matchweek_id: str,
        evidence: WeatherEvidence,
        *,
        location: VenueLocation | None = None,
        created_at_utc: str | None = None,
    ) -> StoredWeatherEvidence:
        from matchvet.artifacts import ArtifactStore
        from matchvet.ingestion import deterministic_identifier

        location_id = self.locations.record(location) if location is not None else None
        evidence_digest = evidence.digest
        weather_id = deterministic_identifier(
            "weather_evidence", f"{matchweek_id}:{evidence.fixture_id}"
        )
        created = (
            _canonical_utc(created_at_utc)
            if created_at_utc
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
        artifact_digest: str | None = None
        capture_id: str | None = None
        response_byte_length: int | None = None
        request_key = _weather_request_key(evidence)
        response_bytes = evidence.response_bytes
        if (
            response_bytes is not None
            and evidence.forecast_model is not None
            and evidence.forecast_issue_time_utc is not None
            and evidence.retrieved_at_utc is not None
            and evidence.forecast_target_time_utc is not None
            and evidence.forecast_interval_start_utc is not None
            and evidence.forecast_interval_end_utc is not None
            and evidence.latitude is not None
            and evidence.longitude is not None
        ):
            assert response_bytes is not None
            artifact = ArtifactStore(self.store).publish_artifact(
                response_bytes,
                "application/json",
                expected_digest=evidence.response_content_sha256,
                retention_class="REUSABLE",
            )
            artifact_digest = artifact.digest
            response_byte_length = len(response_bytes)
            capture_id = deterministic_identifier(
                "weather_capture",
                f"{evidence.fixture_id}:{request_key}:{artifact.digest}",
            )
        with self.store.transaction() as transaction:
            existing = transaction.execute(
                """
                SELECT weather_evidence_id, location_id, capture_id, evidence_state,
                       evidence_digest
                FROM weather_evidence
                WHERE matchweek_id = ? AND target_fixture_id = ?
                """,
                (matchweek_id, evidence.fixture_id),
            ).fetchone()
            if existing is not None:
                if str(existing[4]) != evidence_digest:
                    raise WeatherError("Frozen weather evidence was reused with different content.")
                return StoredWeatherEvidence(
                    str(existing[0]),
                    matchweek_id,
                    evidence.fixture_id,
                    evidence,
                    str(existing[1]) if existing[1] is not None else None,
                    str(existing[2]) if existing[2] is not None else None,
                    str(existing[4]),
                )
            if capture_id is not None and artifact_digest is not None:
                transaction.add_identifier_if_missing(
                    CanonicalIdentifier("weather_capture", capture_id)
                )
                transaction.execute(
                    """
                    INSERT INTO weather_captures (
                        capture_id, target_fixture_id, request_key, locator, forecast_model,
                        forecast_issue_time_utc, forecast_issue_time_source, retrieved_at_utc,
                        response_status, content_sha256, byte_length, artifact_digest,
                        latitude, longitude, forecast_target_time_utc,
                        forecast_interval_start_utc, forecast_interval_end_utc,
                        cutoff_eligibility, attribution, units_json, provenance_json,
                        created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(target_fixture_id, request_key, content_sha256) DO NOTHING
                    """,
                    (
                        capture_id,
                        evidence.fixture_id,
                        request_key,
                        evidence.source_locator or OPEN_METEO_FORECAST_URL,
                        evidence.forecast_model,
                        evidence.forecast_issue_time_utc,
                        evidence.forecast_issue_time_source or "UNKNOWN",
                        evidence.retrieved_at_utc,
                        evidence.response_status or 200,
                        evidence.response_content_sha256,
                        response_byte_length,
                        artifact_digest,
                        evidence.latitude,
                        evidence.longitude,
                        evidence.forecast_target_time_utc,
                        evidence.forecast_interval_start_utc,
                        evidence.forecast_interval_end_utc,
                        evidence.cutoff_eligibility.value,
                        evidence.attribution,
                        _canonical_json(dict(evidence.units)).decode(),
                        _canonical_json(
                            {
                                "location": dict(evidence.location_provenance),
                                "source_key": OPEN_METEO_SOURCE_KEY,
                                "source_locator": evidence.source_locator,
                                "terms": OPEN_METEO_TERMS,
                                "attribution": evidence.attribution,
                            }
                        ).decode(),
                        created,
                    ),
                )
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("weather_evidence", weather_id)
            )
            transaction.execute(
                """
                INSERT INTO weather_evidence (
                    weather_evidence_id, matchweek_id, target_fixture_id, location_id,
                    cutoff_utc, capture_id, evidence_state, evidence_class, cutoff_eligibility,
                    freshness, unknown_reason, target_time_utc, forecast_target_time_utc,
                    forecast_interval_start_utc, forecast_interval_end_utc, forecast_model,
                    forecast_issue_time_utc, forecast_issue_time_source, retrieved_at_utc,
                    latitude, longitude, values_json, units_json, location_provenance_json,
                    attribution, source_locator, response_status, response_content_sha256,
                    eligible_target_match, freshness_age_seconds_at_cutoff, evidence_digest,
                    created_at_utc
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    weather_id,
                    matchweek_id,
                    evidence.fixture_id,
                    location_id,
                    evidence.cutoff_utc,
                    capture_id,
                    evidence.state.value,
                    evidence.evidence_class.value,
                    evidence.cutoff_eligibility.value,
                    evidence.freshness.value,
                    evidence.unknown_reason,
                    evidence.target_time_utc,
                    evidence.forecast_target_time_utc,
                    evidence.forecast_interval_start_utc,
                    evidence.forecast_interval_end_utc,
                    evidence.forecast_model,
                    evidence.forecast_issue_time_utc,
                    evidence.forecast_issue_time_source,
                    evidence.retrieved_at_utc,
                    evidence.latitude,
                    evidence.longitude,
                    _canonical_json(dict(evidence.values)).decode(),
                    _canonical_json(dict(evidence.units)).decode(),
                    _canonical_json(dict(evidence.location_provenance)).decode(),
                    evidence.attribution,
                    evidence.source_locator,
                    evidence.response_status,
                    evidence.response_content_sha256,
                    int(evidence.eligible_target_match),
                    evidence.freshness_age_seconds_at_cutoff,
                    evidence_digest,
                    created,
                ),
            )
        return StoredWeatherEvidence(
            weather_id,
            matchweek_id,
            evidence.fixture_id,
            evidence,
            location_id,
            capture_id,
            evidence_digest,
        )

    def records(self, matchweek_id: str) -> tuple[StoredWeatherEvidence, ...]:
        rows = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT weather_evidence_id, matchweek_id, target_fixture_id, location_id,
                   capture_id, cutoff_utc, evidence_state, cutoff_eligibility, freshness,
                   unknown_reason,
                   target_time_utc, forecast_target_time_utc, forecast_interval_start_utc,
                   forecast_interval_end_utc, forecast_model, forecast_issue_time_utc,
                   forecast_issue_time_source, retrieved_at_utc, latitude, longitude,
                   values_json, units_json, location_provenance_json, attribution,
                   source_locator, response_status, response_content_sha256,
                   eligible_target_match, freshness_age_seconds_at_cutoff, evidence_digest
            FROM weather_evidence WHERE matchweek_id = ? ORDER BY target_fixture_id
            """,
                (matchweek_id,),
            )
            .fetchall()
        )
        records: list[StoredWeatherEvidence] = []
        for row in rows:
            values = json.loads(str(row[20]))
            units = json.loads(str(row[21]))
            provenance = json.loads(str(row[22]))
            if (
                not isinstance(values, dict)
                or not isinstance(units, dict)
                or not isinstance(provenance, dict)
            ):
                raise WeatherError("Stored weather payload is malformed.")
            evidence = WeatherEvidence(
                fixture_id=str(row[2]),
                target_time_utc=str(row[10]),
                cutoff_utc=str(row[5]),
                state=EvidenceState(str(row[6])),
                cutoff_eligibility=CutoffEligibility(str(row[7])),
                freshness=Freshness(str(row[8])),
                unknown_reason=str(row[9]) if row[9] is not None else None,
                forecast_target_time_utc=(str(row[11]) if row[11] is not None else None),
                forecast_interval_start_utc=(str(row[12]) if row[12] is not None else None),
                forecast_interval_end_utc=(str(row[13]) if row[13] is not None else None),
                forecast_model=str(row[14]) if row[14] is not None else None,
                forecast_issue_time_utc=str(row[15]) if row[15] is not None else None,
                forecast_issue_time_source=str(row[16]) if row[16] is not None else None,
                retrieved_at_utc=str(row[17]) if row[17] is not None else None,
                latitude=float(row[18]) if row[18] is not None else None,
                longitude=float(row[19]) if row[19] is not None else None,
                values=values,
                units=units,
                location_provenance=provenance,
                attribution=str(row[23]),
                source_locator=str(row[24]) if row[24] is not None else None,
                response_status=int(row[25]) if row[25] is not None else None,
                response_content_sha256=str(row[26]) if row[26] is not None else None,
                eligible_target_match=bool(row[27]),
                freshness_age_seconds_at_cutoff=(float(row[28]) if row[28] is not None else None),
            )
            records.append(
                StoredWeatherEvidence(
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    evidence,
                    str(row[3]) if row[3] is not None else None,
                    str(row[4]) if row[4] is not None else None,
                    str(row[29]),
                )
            )
        return tuple(records)

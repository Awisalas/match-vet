"""Exact F11 immutable codecs and prospective context representation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.error import HTTPError

from matchvet.evidence import CutoffEligibility
from matchvet.matchweek_membership import canonical_json
from matchvet.weather import (
    WeatherClient,
    WeatherHTTPResponse,
    WeatherParseError,
    WeatherRequest,
    WeatherUnavailable,
    parse_open_meteo_response,
)
from matchvet.workload import CanonicalFixture, FixtureProvenance

EVIDENCE_MEDIA_TYPE = "application/vnd.matchvet.f11-evidence-set.v3+json"
HISTORY_MEDIA_TYPE = "application/vnd.matchvet.f11-fixture-history.v2+json"
CAUSAL_EVIDENCE_MEDIA_TYPE = "application/vnd.matchvet.f11-evidence-set.v4+json"
CAUSAL_HISTORY_MEDIA_TYPE = "application/vnd.matchvet.f11-candidate-history.v1+json"
RESPONSE_MEDIA_TYPE = "application/vnd.matchvet.f11-weather-response.v2+json"


class F11Error(ValueError):
    """An exact F11 predecessor, evidence set or provenance reference is invalid."""


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def prospective_context(value: dict[str, Any]) -> dict[str, Any]:
    """Candidate context has no local-time qualification, including UNKNOWN values."""
    result = dict(value)
    result["cutoff_eligibility"] = "UNQUALIFIED"
    if "freshness" in result:
        result["freshness"] = "UNKNOWN"
    return result


@dataclass(frozen=True)
class F11EvidenceSet:
    """Immutable canonical value; dictionary access returns a detached copy."""

    canonical_bytes: bytes

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    @property
    def digest(self) -> str:
        return _digest(self.canonical_bytes)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.canonical_bytes)
        return value


@dataclass(frozen=True)
class _RetainedWeatherClient:
    content: bytes | None
    retrieved_at_utc: str | None
    response_status: int | None

    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
        if self.content is None:
            raise WeatherUnavailable("Retained acquisition was unavailable.")
        if self.retrieved_at_utc is None or self.response_status is None:
            raise F11Error("Weather response metadata is missing.")
        return WeatherHTTPResponse(
            content=self.content,
            retrieved_at_utc=self.retrieved_at_utc,
            response_status=self.response_status,
            url=request.url,
        )


def _at_cutoff(fixture: CanonicalFixture, cutoff: str) -> CanonicalFixture:
    boundary = datetime.fromisoformat(cutoff)
    eligibility = CutoffEligibility.INDETERMINATE
    if fixture.observed_at_utc is not None:
        times = [fixture.observed_at_utc]
        times.extend(p.published_at_utc for p in fixture.provenance if p.published_at_utc)
        eligibility = (
            CutoffEligibility.POST_CUTOFF
            if any(datetime.fromisoformat(t) > boundary for t in times)
            else CutoffEligibility.CUTOFF_VALID
        )
    return replace(fixture, cutoff_eligibility=eligibility)


def _history_values(encoded: bytes) -> tuple[CanonicalFixture, ...]:
    values = json.loads(encoded)
    result = []
    for value in values:
        value["provenance"] = tuple(FixtureProvenance(**p) for p in value["provenance"])
        result.append(CanonicalFixture(**value))
    return tuple(result)


@dataclass
class _AcquisitionClient:
    client: WeatherClient
    guard: Callable[[], object] | None = None
    error_type: str | None = None
    response_status: int | None = None
    causal: bool = False
    enforce_cutoff: bool = True

    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
        if self.guard is not None:
            self.guard()
        try:
            response = self.client.fetch(request, refresh=refresh)
        except Exception as error:
            self.error_type = type(error).__name__
            http_error = error if isinstance(error, HTTPError) else error.__cause__
            if isinstance(http_error, HTTPError):
                self.response_status = http_error.code
            raise
        finally:
            if self.guard is not None:
                self.guard()
        if (
            self.guard is not None
            and not self.causal
            and self.enforce_cutoff
            and (
                datetime.fromisoformat(response.retrieved_at_utc)
                > datetime.fromisoformat(request.cutoff_utc)
            )
        ):
            raise F11Error("Weather retrieval is after the common cutoff.")
        self.response_status = response.response_status
        return response


def _parse_error_type(
    content: bytes, request: WeatherRequest, retrieved: str, *, causal: bool = False
) -> str | None:
    try:
        parse_open_meteo_response(
            content,
            request,
            retrieved_at_utc=retrieved,
            selection_contract="matchvet-causal-selection-v2"
            if causal
            else "postcommit-upper-bound-v1",
        )
    except WeatherParseError as error:
        return type(error).__name__
    return None

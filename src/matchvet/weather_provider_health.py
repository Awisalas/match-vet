"""F09 health observations from the existing T08 Open-Meteo request and parser seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.error import HTTPError

from matchvet.evidence import CutoffEligibility
from matchvet.provider_health import (
    CapabilityAvailabilityAssessment,
    CapabilityAvailabilityState,
    CapabilityCoverageEvidenceReference,
    CapabilityIdentity,
    CoverageApplicability,
    CoverageAssessment,
    CoverageState,
    CoverageWitness,
    EvidenceBasis,
    FacetApplicability,
    FailureAssessment,
    FailureReasonCode,
    FailureState,
    FreshnessAssessment,
    FreshnessState,
    NamedSelectorFacet,
    OtherVersionedEvidenceReference,
    PermissionPolicyReference,
    ProviderHealthRecord,
    ProviderIdentity,
    ReachabilityAssessment,
    ReachabilityState,
    RequestedScope,
    ScopeContract,
    ScopeFacet,
    StructuralValidityAssessment,
    StructuralValidityState,
    SubjectIdentifier,
    SubjectKind,
    UsePermissionAssessment,
    UsePermissionState,
    UtcInterval,
)

if TYPE_CHECKING:
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import WeatherEvidence, WeatherHTTPResponse, WeatherRequest

OPEN_METEO_PROVIDER_ID = "open-meteo"
WEATHER_CAPABILITY_ID = "weather-forecast"
WEATHER_INTENDED_USE_ID = "matchvet:research-only:t08-weather:non-commercial"


def open_meteo_requested_scope(request: WeatherRequest) -> RequestedScope:
    """Retain the exact target, venue, coordinates, variables, model, and cutoff query."""
    return RequestedScope(
        scope_kind="open-meteo-weather-query",
        competition=ScopeFacet.not_applicable(),
        season=ScopeFacet.not_applicable(),
        time=ScopeFacet.known(UtcInterval(request.interval_start_utc, request.interval_end_utc)),
        subjects=ScopeFacet.known(
            (
                SubjectIdentifier(SubjectKind.MATCH, request.fixture_id),
                SubjectIdentifier(SubjectKind.VENUE, request.location.venue_id),
            )
        ),
        selectors=(
            NamedSelectorFacet("request_url", ScopeFacet.known((request.url,))),
            NamedSelectorFacet("request_cache_key", ScopeFacet.known((request.cache_key,))),
            NamedSelectorFacet("cutoff_utc", ScopeFacet.known((request.cutoff_utc,))),
        ),
    )


class OpenMeteoHealthRecorder:
    """Persist observed health before T08 returns weather evidence to a consumer.

    This recorder accepts the real parser result; health never manufactures or
    publishes weather evidence. T08 has no source-age freshness policy, so an
    acquisition observation retains UNKNOWN freshness.
    """

    def __init__(
        self, repository: ProviderHealthRepository, *, clock: Callable[[], str] | None = None
    ) -> None:
        self.repository = repository
        self._clock = clock
        self._records: list[ProviderHealthRecord] = []

    @property
    def records(self) -> tuple[ProviderHealthRecord, ...]:
        return tuple(self._records)

    def record(
        self,
        request: WeatherRequest,
        response: WeatherHTTPResponse | None = None,
        forecast: WeatherEvidence | None = None,
        *,
        error: Exception | None = None,
    ) -> ProviderHealthRecord:
        from matchvet.weather import WeatherCoverageError, WeatherParseError, WeatherPolicyError

        http_error = (
            error
            if isinstance(error, HTTPError)
            else error.__cause__
            if error is not None and isinstance(error.__cause__, HTTPError)
            else None
        )
        status = response.response_status if response else http_error.code if http_error else None
        denied = isinstance(error, WeatherPolicyError) or status in (401, 403)
        coverage_missing = isinstance(error, WeatherCoverageError) and response is not None
        malformed = isinstance(error, WeatherParseError) and not coverage_missing
        post_cutoff = (
            forecast is not None and forecast.cutoff_eligibility is CutoffEligibility.POST_CUTOFF
        )
        unavailable = (
            (error is not None or (status is not None and status != 200))
            and not denied
            and not malformed
            and not coverage_missing
        )
        if (
            not denied
            and not unavailable
            and not malformed
            and not coverage_missing
            and (response is None or forecast is None)
        ):
            raise ValueError("A weather health observation requires a response and parser result.")
        scope = open_meteo_requested_scope(request)
        checked = (
            self._clock()
            if self._clock is not None
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
        content_digest = hashlib.sha256(response.content).hexdigest() if response else None
        if http_error is not None and http_error.url != request.url:
            raise ValueError("Weather HTTP error does not match the exact requested scope.")
        if response is not None and response.url is not None and response.url != request.url:
            raise ValueError("Weather response URL does not match the exact requested scope.")
        if forecast is not None and (
            response is None
            or error is not None
            or response.response_status != 200
            or (
                forecast.fixture_id,
                forecast.target_time_utc,
                forecast.cutoff_utc,
                forecast.retrieved_at_utc,
                forecast.response_content_sha256,
                forecast.source_locator,
            )
            != (
                request.fixture_id,
                request.target_time_utc,
                request.cutoff_utc,
                response.retrieved_at_utc,
                content_digest,
                request.url,
            )
            or forecast.location_provenance != request.location.provenance
        ):
            raise ValueError(
                "Weather parser result does not match its exact request scope and response."
            )
        event = json.dumps(
            {
                "request_scope_id": scope.scope_id,
                "checked_at_utc": checked,
                "response_digest": content_digest,
                "response_status": status,
                "retrieved_at_utc": response.retrieved_at_utc if response else None,
                "error_type": type(error).__name__ if error else None,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        event_digest = "sha256:" + hashlib.sha256(event.encode()).hexdigest()
        reference = OtherVersionedEvidenceReference(
            evidence_id=event_digest,
            evidence_kind="t08-open-meteo-fetch-parse-observation",
            version="v1",
            provider_id=OPEN_METEO_PROVIDER_ID,
            capability_id=WEATHER_CAPABILITY_ID,
            scope_id=scope.scope_id,
            digest=event_digest,
        )
        basis = EvidenceBasis(
            OPEN_METEO_PROVIDER_ID,
            WEATHER_CAPABILITY_ID,
            scope.scope_id,
            (reference,),
            source_as_of_utc=forecast.forecast_issue_time_utc if forecast else None,
        )
        coverage = CoverageAssessment(CoverageState.UNKNOWN)
        provenance: tuple[
            OtherVersionedEvidenceReference | CapabilityCoverageEvidenceReference, ...
        ] = (reference,)
        if forecast is not None or coverage_missing:
            assert content_digest is not None
            if forecast is None:
                covered_variables: tuple[str, ...] = ()
                assert isinstance(error, WeatherCoverageError)
                gaps: tuple[str, ...] = error.known_gap_ids
            else:
                covered_variables = tuple(
                    variable for variable in request.variables if variable in forecast.values
                )
                gaps = tuple(
                    variable for variable in request.variables if variable not in forecast.values
                )
                interval_covered = (
                    forecast.forecast_interval_start_utc is not None
                    and forecast.forecast_interval_end_utc is not None
                    and forecast.forecast_interval_start_utc <= request.interval_start_utc
                    and forecast.forecast_interval_end_utc >= request.interval_end_utc
                )
                if not interval_covered:
                    gaps = (*gaps, "target_interval")
            complete = not gaps
            coverage_reference = CapabilityCoverageEvidenceReference(
                evidence_id=event_digest + ":coverage",
                evidence_kind="t08-open-meteo-hourly-coverage",
                version="v1",
                provider_id=OPEN_METEO_PROVIDER_ID,
                capability_id=WEATHER_CAPABILITY_ID,
                scope_id=scope.scope_id,
                digest=content_digest,
                scope_complete=complete,
                enumeration_complete=True,
                covered_extent_ids=covered_variables,
                known_gap_ids=gaps,
            )
            coverage = CoverageAssessment(
                CoverageState.COMPLETE if complete else CoverageState.PARTIAL,
                CoverageWitness(
                    OPEN_METEO_PROVIDER_ID,
                    WEATHER_CAPABILITY_ID,
                    scope.scope_id,
                    (coverage_reference,),
                ),
            )
            provenance = (reference, coverage_reference)
        availability = CapabilityAvailabilityState.UNKNOWN
        structure = StructuralValidityState.UNKNOWN
        reason: str | None = None
        if denied:
            reason = "PERMISSION_FAILED"
        elif coverage_missing:
            assert isinstance(error, WeatherCoverageError)
            reason = error.reason_code
        elif malformed:
            structure = StructuralValidityState.INVALID
            reason = "MALFORMED_RESPONSE"
        elif unavailable:
            availability = CapabilityAvailabilityState.UNAVAILABLE
            reason = "WEATHER_UNAVAILABLE"
        else:
            availability = CapabilityAvailabilityState.AVAILABLE
            structure = StructuralValidityState.VALID
            if post_cutoff:
                reason = "FORECAST_POST_CUTOFF"
        failure = (
            FailureAssessment(FailureState.FAILED, (FailureReasonCode(reason),), basis)
            if reason is not None
            else FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=basis)
        )
        record = ProviderHealthRecord(
            provider=ProviderIdentity(OPEN_METEO_PROVIDER_ID, "open-meteo-forecast"),
            capability=CapabilityIdentity(
                WEATHER_CAPABILITY_ID,
                ScopeContract(
                    FacetApplicability.NOT_APPLICABLE,
                    FacetApplicability.NOT_APPLICABLE,
                    FacetApplicability.APPLICABLE,
                    FacetApplicability.APPLICABLE,
                    ("cutoff_utc", "request_cache_key", "request_url"),
                    CoverageApplicability.APPLICABLE,
                ),
            ),
            requested_scope=scope,
            intended_use_id=WEATHER_INTENDED_USE_ID,
            checked_at_utc=checked,
            use_permission=UsePermissionAssessment(
                UsePermissionState.NOT_PERMITTED if denied else UsePermissionState.PERMITTED,
                PermissionPolicyReference(
                    "f08-open-meteo-non-commercial", "v1", WEATHER_INTENDED_USE_ID
                ),
            ),
            reachability=(
                ReachabilityAssessment(ReachabilityState.UNKNOWN)
                if status is None
                else ReachabilityAssessment(ReachabilityState.REACHABLE, basis)
            ),
            capability_availability=CapabilityAvailabilityAssessment(
                availability,
                basis if availability is not CapabilityAvailabilityState.UNKNOWN else None,
            ),
            structural_validity=StructuralValidityAssessment(
                structure,
                basis if structure is not StructuralValidityState.UNKNOWN else None,
            ),
            freshness=FreshnessAssessment(FreshnessState.UNKNOWN),
            coverage=coverage,
            failure=failure,
            provenance=provenance,
        )
        if self._clock is not None:
            self._clock()
        self.repository.persist_many((record,))
        self._records.append(record)
        return record

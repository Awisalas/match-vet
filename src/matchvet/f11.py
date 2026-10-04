"""F06/F07-native immutable workload and weather research evidence.

The first build retains acquisition for an exact request. Retries replay that
artifact, including F09 observations, without observing a new provider state.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any
from urllib.error import HTTPError

from matchvet.artifacts import ArtifactStore
from matchvet.evidence import CutoffEligibility
from matchvet.f12 import (
    AttemptOutcome,
    AttemptUsability,
    ContextualAttemptRepository,
    ContextualResearchAttempt,
    F12Error,
)
from matchvet.match_evidence_cutoff import MatchEvidenceCutoff, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import (
    MatchweekMembershipFreeze,
    MembershipState,
    canonical_json,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health import (
    CapabilityCoverageEvidenceReference,
    OtherVersionedEvidenceReference,
)
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import Store
from matchvet.weather import (
    VenueLocation,
    WeatherClient,
    WeatherEvidenceBuilder,
    WeatherHTTPResponse,
    WeatherParseError,
    WeatherRequest,
    WeatherTarget,
    WeatherUnavailable,
    parse_open_meteo_response,
)
from matchvet.weather_provider_health import open_meteo_requested_scope
from matchvet.workload import (
    CanonicalFixture,
    FixtureProvenance,
    WorkloadCalculator,
    WorkloadRules,
    _canonical_utc,
    load_canonical_fixture_history,
)

EVIDENCE_MEDIA_TYPE = "application/vnd.matchvet.f11-evidence-set.v3+json"
HISTORY_MEDIA_TYPE = "application/vnd.matchvet.f11-fixture-history.v2+json"
RESPONSE_MEDIA_TYPE = "application/vnd.matchvet.f11-weather-response.v2+json"


class F11Error(ValueError):
    """An exact F11 predecessor, evidence set or provenance reference is invalid."""


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


@dataclass
class _AcquisitionClient:
    client: WeatherClient
    error_type: str | None = None
    response_status: int | None = None

    def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
        try:
            response = self.client.fetch(request, refresh=refresh)
        except Exception as error:
            self.error_type = type(error).__name__
            http_error = error if isinstance(error, HTTPError) else error.__cause__
            if isinstance(http_error, HTTPError):
                self.response_status = http_error.code
            raise
        self.response_status = response.response_status
        return response


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


def _parse_error_type(content: bytes, request: WeatherRequest, retrieved: str) -> str | None:
    try:
        parse_open_meteo_response(content, request, retrieved_at_utc=retrieved)
    except WeatherParseError as error:
        return type(error).__name__
    return None


class F11EvidenceRepository:
    """Own exact joins, acquisition retention and verified evidence-set replay."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)

    def _inputs(
        self, freeze_id: str, policy_digest: str
    ) -> tuple[MatchweekMembershipFreeze, tuple[MatchEvidenceCutoff, ...]]:
        freeze = MatchweekMembershipRepository(self.store).get_by_id(freeze_id)
        if freeze is None:
            raise F11Error("Exact F06 freeze is missing.")
        cutoffs = MatchEvidenceCutoffRepository(self.store).replay_for_freeze(
            freeze_id, policy_digest
        )
        members = {
            m.membership_id: m for m in freeze.memberships if m.decision is MembershipState.INCLUDED
        }
        if len(cutoffs) != len(members) or {c.membership_id for c in cutoffs} != set(members):
            raise F11Error("Exactly one F07 cutoff is required per INCLUDED membership.")
        for cutoff in cutoffs:
            member = members[cutoff.membership_id]
            if (
                cutoff.freeze_id,
                cutoff.freeze_digest,
                cutoff.membership_digest,
                cutoff.fixture_id,
                cutoff.fixture_revision_ref,
                cutoff.fixture_revision_digest,
                cutoff.policy_digest,
            ) != (
                freeze.freeze_id,
                freeze.freeze_digest,
                member.membership_digest,
                member.fixture_id,
                member.controlling_revision_id,
                member.controlling_revision_digest,
                policy_digest,
            ):
                raise F11Error("F07 cutoff differs from exact F06 membership or policy.")
        return freeze, tuple(sorted(cutoffs, key=lambda c: c.membership_id))

    def build(
        self,
        freeze_id: str,
        policy_digest: str,
        *,
        weather_client: WeatherClient | None,
        context_fixtures: Iterable[CanonicalFixture] = (),
        locations: Mapping[str, VenueLocation] | None = None,
        rules: WorkloadRules | None = None,
    ) -> F11EvidenceSet:
        """Build once for the exact request, or replay its retained acquisition."""
        freeze, cutoffs = self._inputs(freeze_id, policy_digest)
        context = tuple(sorted(context_fixtures, key=lambda f: _bytes(f.to_dict())))
        venues = dict(locations or {})
        rules = rules or WorkloadRules()
        request = {
            "freeze_id": freeze_id,
            "freeze_digest": freeze.freeze_digest,
            "policy_digest": policy_digest,
            "rules": asdict(rules),
            "context": [f.to_dict() for f in context],
            "locations": {key: value.to_dict() for key, value in sorted(venues.items())},
        }
        request_digest = _digest(_bytes(request))
        existing: list[F11EvidenceSet] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type == EVIDENCE_MEDIA_TYPE:
                value = self._read(metadata.digest, EVIDENCE_MEDIA_TYPE)
                candidate = json.loads(value)
                if candidate["request_digest"] == request_digest:
                    existing.append(
                        self.replay(
                            metadata.digest, freeze_id=freeze_id, policy_digest=policy_digest
                        )
                    )
        if len(existing) > 1:
            raise F11Error("Conflicting evidence sets name the same exact request.")
        if existing:
            return existing[0]
        history = load_canonical_fixture_history(
            self.store, season=freeze.season, context_fixtures=context
        )
        history_bytes = _bytes(sorted((f.to_dict() for f in history), key=_bytes))
        history_digest = self.artifacts.publish_artifact(history_bytes, HISTORY_MEDIA_TYPE).digest
        matches = []
        contextual_attempts = ContextualAttemptRepository(self.store)
        for cutoff in cutoffs:
            per_match = tuple(_at_cutoff(f, cutoff.cutoff_at_utc) for f in history)
            target = self._target(per_match, cutoff)
            workload = WorkloadCalculator(
                per_match, cutoff_utc=cutoff.cutoff_at_utc, rules=rules
            ).calculate(target)
            location = venues.get(cutoff.fixture_id)
            weather_request = None
            request_scope = None
            if (
                location is not None
                and location.available
                and datetime.fromisoformat(location.observed_at_utc)
                <= datetime.fromisoformat(cutoff.cutoff_at_utc)
            ):
                weather_request = WeatherRequest(
                    cutoff.fixture_id,
                    target.kickoff_utc or "",
                    cutoff.cutoff_at_utc,
                    location,
                )
                request_scope = open_meteo_requested_scope(weather_request)
            retained_attempt = (
                contextual_attempts.find_for_request(
                    fixture_id=cutoff.fixture_id,
                    cutoff_id=cutoff.cutoff_id,
                    cutoff_digest=cutoff.digest,
                    requested_scope_id=request_scope.scope_id,
                )
                if request_scope is not None
                else None
            )
            acquisition = (
                _AcquisitionClient(weather_client)
                if weather_client is not None and retained_attempt is None
                else None
            )
            if retained_attempt is not None:
                retained_response = None
                if retained_attempt.response_artifact_digest is not None:
                    envelope = json.loads(
                        self._read(retained_attempt.response_artifact_digest, RESPONSE_MEDIA_TYPE)
                    )
                    retained_response = base64.b64decode(envelope["body_base64"], validate=True)
                replay_client: WeatherClient = _RetainedWeatherClient(
                    retained_response,
                    retained_attempt.retrieved_at_utc,
                    retained_attempt.response_status,
                )
                builder = WeatherEvidenceBuilder(replay_client)
            else:
                builder = WeatherEvidenceBuilder(
                    acquisition,
                    provider_health_repository=ProviderHealthRepository(self.store),
                )
            batch = builder.build(
                (
                    WeatherTarget(
                        target.fixture_id,
                        target.kickoff_utc or "",
                        cutoff.cutoff_at_utc,
                        venues.get(target.fixture_id),
                    ),
                )
            )
            weather = batch.evidence[0]
            error_type = (
                retained_attempt.error_type
                if retained_attempt is not None
                else acquisition.error_type
                if acquisition
                else None
            )
            response_digest = None
            if weather.response_bytes is not None:
                response_digest = self.artifacts.publish_artifact(
                    _bytes(
                        {
                            "schema_version": 2,
                            "response_content_sha256": _digest(weather.response_bytes),
                            "body_base64": base64.b64encode(weather.response_bytes).decode("ascii"),
                        }
                    ),
                    RESPONSE_MEDIA_TYPE,
                ).digest
                if weather.response_status == 200:
                    if weather_request is None:
                        raise F11Error("Captured weather response has no exact request.")
                    error_type = _parse_error_type(
                        weather.response_bytes,
                        weather_request,
                        weather.retrieved_at_utc or "",
                    )
            contextual_attempt = None
            if retained_attempt is not None:
                typed_attempt = retained_attempt
                contextual_attempt = {
                    "attempt_id": typed_attempt.attempt_id,
                    "digest": typed_attempt.digest,
                }
            elif batch.provider_health_records:
                if len(batch.provider_health_records) != 1:
                    raise F11Error("F09 must retain exactly one health record per weather request.")
                if weather_request is None:
                    raise F11Error("F09 health exists without an exact Open-Meteo request.")
                try:
                    typed_attempt = ContextualResearchAttempt.create(
                        cutoff=cutoff,
                        request=weather_request,
                        weather=weather,
                        health=batch.provider_health_records[0],
                        response_artifact_digest=response_digest,
                        error_type=error_type,
                        response_status=(
                            acquisition.response_status if acquisition is not None else None
                        ),
                    )
                    typed_attempt = contextual_attempts.publish(typed_attempt)
                except F12Error as error:
                    raise F11Error("F12 contextual attempt validation failed.") from error
                contextual_attempt = {
                    "attempt_id": typed_attempt.attempt_id,
                    "digest": typed_attempt.digest,
                }
            matches.append(
                {
                    "cutoff": {
                        **asdict(cutoff),
                        "cutoff_id": cutoff.cutoff_id,
                        "digest": cutoff.digest,
                    },
                    "workload": workload.to_dict(),
                    "weather": weather.to_dict(),
                    "provider_health_digests": sorted(
                        {r.digest for r in batch.provider_health_records}
                        | (
                            {retained_attempt.provider_health_digest}
                            if retained_attempt is not None
                            else set()
                        )
                    ),
                    "response_artifact_digest": response_digest,
                    "contextual_attempt": contextual_attempt,
                }
            )
        payload = {
            "schema_version": 3,
            "freeze_id": freeze_id,
            "freeze_digest": freeze.freeze_digest,
            "policy_digest": policy_digest,
            "request_digest": request_digest,
            "request": request,
            "history_artifact_digest": history_digest,
            "matches": matches,
        }
        evidence = F11EvidenceSet(_bytes(payload))
        # Validate all references before publication, including caller context.
        self._validate(evidence, freeze_id, policy_digest)
        self.artifacts.publish_artifact(evidence.to_bytes(), EVIDENCE_MEDIA_TYPE)
        return self.replay(evidence.digest, freeze_id=freeze_id, policy_digest=policy_digest)

    def replay(self, digest: str, *, freeze_id: str, policy_digest: str) -> F11EvidenceSet:
        """Replay named bytes and their complete exact predecessor/provenance chain."""
        evidence = F11EvidenceSet(self._read(digest, EVIDENCE_MEDIA_TYPE))
        try:
            self._validate(evidence, freeze_id, policy_digest)
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            raise F11Error("Malformed F11 evidence set.") from error
        return evidence

    def _read(self, digest: str, media_type: str) -> bytes:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            media_type,
            "PROTECTED",
        ):
            raise F11Error("Missing or wrong F11 artifact reference.")
        return self.artifacts.read_artifact(digest)

    def _target(
        self, history: tuple[CanonicalFixture, ...], cutoff: MatchEvidenceCutoff
    ) -> CanonicalFixture:
        targets = [
            f
            for f in history
            if (f.fixture_id, f.revision_id, f.revision_digest)
            == (cutoff.fixture_id, cutoff.fixture_revision_ref, cutoff.fixture_revision_digest)
        ]
        if len(targets) != 1 or targets[0].effective_cutoff_eligibility is not (
            CutoffEligibility.CUTOFF_VALID
        ):
            raise F11Error("Exact controlling revision is missing, duplicated or post-cutoff.")
        target = targets[0]
        row = (
            self.store._connection_for_repository()
            .execute(
                """SELECT f.home_team_id, f.away_team_id, r.kickoff_utc, r.fixture_status,
                      r.revision_digest
               FROM fixture_revisions r JOIN fixtures f ON f.fixture_id = r.fixture_id
               WHERE r.revision_id = ? AND r.fixture_id = ?""",
                (cutoff.fixture_revision_ref, cutoff.fixture_id),
            )
            .fetchone()
        )
        if row is None or (
            target.home_team_id,
            target.away_team_id,
            target.kickoff_utc,
            str(target.status),
            target.revision_digest,
        ) != (str(row[0]), str(row[1]), _canonical_utc(str(row[2])), str(row[3]), str(row[4])):
            raise F11Error("Retained target differs from its canonical controlling revision.")
        return targets[0]

    def _validate(self, evidence: F11EvidenceSet, freeze_id: str, policy_digest: str) -> None:
        value = evidence.to_dict()
        if (
            _bytes(value) != evidence.to_bytes()
            or set(value)
            != {
                "schema_version",
                "freeze_id",
                "freeze_digest",
                "policy_digest",
                "request_digest",
                "request",
                "history_artifact_digest",
                "matches",
            }
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 3
        ):
            raise F11Error("Noncanonical or unsupported F11 evidence contract.")
        freeze, cutoffs = self._inputs(freeze_id, policy_digest)
        if (value["freeze_id"], value["freeze_digest"], value["policy_digest"]) != (
            freeze.freeze_id,
            freeze.freeze_digest,
            policy_digest,
        ):
            raise F11Error("Evidence set differs from requested freeze or policy.")
        request = value["request"]
        if value["request_digest"] != _digest(_bytes(request)) or (
            request["freeze_id"],
            request["freeze_digest"],
            request["policy_digest"],
        ) != (freeze_id, freeze.freeze_digest, policy_digest):
            raise F11Error("F11 request identity differs.")
        rule_values = dict(request["rules"])
        rule_values["recent_windows_days"] = tuple(rule_values["recent_windows_days"])
        rules = WorkloadRules(**rule_values)
        history = _history_values(self._read(value["history_artifact_digest"], HISTORY_MEDIA_TYPE))
        context = _history_values(_bytes(request["context"]))
        referenced_history = load_canonical_fixture_history(
            self.store, season=freeze.season, context_fixtures=context
        )
        self._verify_history(history, referenced_history, context)
        for fixture in history:
            for provenance in fixture.provenance:
                self._capture(
                    provenance.source_capture_id,
                    provenance.observed_at_utc,
                    provenance.published_at_utc,
                    verify_publication=True,
                )
        for location in request["locations"].values():
            self._capture(location["source_capture_id"], location["observed_at_utc"])
        if len(value["matches"]) != len(cutoffs):
            raise F11Error("Evidence set lacks exact INCLUDED coverage.")
        for match, cutoff in zip(value["matches"], cutoffs, strict=True):
            if set(match) != {
                "cutoff",
                "workload",
                "weather",
                "provider_health_digests",
                "response_artifact_digest",
                "contextual_attempt",
            } or match["cutoff"] != {
                **asdict(cutoff),
                "cutoff_id": cutoff.cutoff_id,
                "digest": cutoff.digest,
            }:
                raise F11Error("Evidence cutoff/membership/revision differs.")
            per_match = tuple(_at_cutoff(f, cutoff.cutoff_at_utc) for f in history)
            target = self._target(per_match, cutoff)
            workload = WorkloadCalculator(
                per_match, cutoff_utc=cutoff.cutoff_at_utc, rules=rules
            ).calculate(target)
            if match["workload"] != json.loads(_bytes(workload.to_dict())):
                raise F11Error("Retained workload differs from exact cutoff history.")
            weather = match["weather"]
            if (weather["cutoff_utc"], weather["target_time_utc"]) != (
                workload.cutoff_utc,
                target.kickoff_utc,
            ):
                raise F11Error("Weather differs from exact match cutoff.")
            location_value = request["locations"].get(cutoff.fixture_id)
            location = VenueLocation(**location_value) if location_value is not None else None
            if weather["location_provenance"] != (dict(location.provenance) if location else {}):
                raise F11Error("Weather location provenance differs.")
            response_artifact_digest = match["response_artifact_digest"]
            response_digest = weather["response_content_sha256"]
            response = None
            if response_artifact_digest is not None:
                envelope_bytes = self._read(response_artifact_digest, RESPONSE_MEDIA_TYPE)
                envelope = json.loads(envelope_bytes)
                if (
                    _bytes(envelope) != envelope_bytes
                    or set(envelope) != {"schema_version", "response_content_sha256", "body_base64"}
                    or type(envelope["schema_version"]) is not int
                    or envelope["schema_version"] != 2
                ):
                    raise F11Error("Malformed weather response envelope.")
                response = base64.b64decode(envelope["body_base64"], validate=True)
                if _digest(response) != response_digest or (
                    envelope["response_content_sha256"] != response_digest
                ):
                    raise F11Error("Weather response reference differs.")
            elif weather["response_content_sha256"] is not None:
                raise F11Error("Weather response artifact is missing.")
            retained_client = (
                None
                if weather["unknown_reason"] == "WEATHER_CLIENT_UNAVAILABLE"
                else _RetainedWeatherClient(
                    response, weather["retrieved_at_utc"], weather["response_status"]
                )
            )
            expected = (
                WeatherEvidenceBuilder(retained_client)
                .build(
                    (
                        WeatherTarget(
                            cutoff.fixture_id,
                            target.kickoff_utc or "",
                            cutoff.cutoff_at_utc,
                            location,
                        ),
                    )
                )
                .evidence[0]
            )
            if weather != expected.to_dict():
                raise F11Error("Weather differs from its retained acquisition.")
            attempted = (
                location is not None
                and location.available
                and retained_client is not None
                and datetime.fromisoformat(location.observed_at_utc)
                <= datetime.fromisoformat(cutoff.cutoff_at_utc)
            )
            if len(match["provider_health_digests"]) != int(attempted):
                raise F11Error("F09 health does not cover the retained weather attempt.")
            if (match["contextual_attempt"] is not None) != attempted:
                raise F11Error("F12 attempt presence differs from whether a request was performed.")
            for health_digest in match["provider_health_digests"]:
                record = ProviderHealthRepository(self.store).get(health_digest)
                if (
                    record is None
                    or location is None
                    or record.requested_scope
                    != (
                        open_meteo_requested_scope(
                            WeatherRequest(
                                cutoff.fixture_id,
                                target.kickoff_utc or "",
                                cutoff.cutoff_at_utc,
                                location,
                            )
                        )
                    )
                ):
                    raise F11Error("F09 health reference is missing or has the wrong scope.")
                for reference in record.provenance:
                    if isinstance(reference, CapabilityCoverageEvidenceReference) and (
                        reference.digest != response_digest
                    ):
                        raise F11Error("F09 health describes a different weather response.")
                attempt_ref = match["contextual_attempt"]
                if not isinstance(attempt_ref, dict) or set(attempt_ref) != {
                    "attempt_id",
                    "digest",
                }:
                    raise F11Error("F12 attempt reference is missing or malformed.")
                try:
                    typed_attempt = ContextualAttemptRepository(self.store).get(
                        attempt_ref["attempt_id"]
                    )
                except F12Error as error:
                    raise F11Error("F12 attempt artifact is missing or corrupt.") from error
                if attempt_ref["digest"] != typed_attempt.digest:
                    raise F11Error("F12 attempt digest reference differs.")
                if response is not None:
                    expected_error = (
                        _parse_error_type(
                            response,
                            WeatherRequest(
                                cutoff.fixture_id,
                                target.kickoff_utc or "",
                                cutoff.cutoff_at_utc,
                                location,
                            ),
                            weather["retrieved_at_utc"],
                        )
                        if weather["response_status"] == 200
                        else None
                    )
                    if typed_attempt.response_status != weather["response_status"] or (
                        typed_attempt.error_type != expected_error
                    ):
                        raise F11Error("F09 acquisition metadata differs from its response.")
                event = {
                    "request_scope_id": record.requested_scope.scope_id,
                    "checked_at_utc": record.checked_at_utc,
                    "response_digest": response_digest,
                    "response_status": typed_attempt.response_status,
                    "retrieved_at_utc": weather["retrieved_at_utc"],
                    "error_type": typed_attempt.error_type,
                }
                event_digest = "sha256:" + _digest(_bytes(event))
                events = [
                    r for r in record.provenance if isinstance(r, OtherVersionedEvidenceReference)
                ]
                if len(events) != 1 or events[0].digest != event_digest:
                    raise F11Error("F09 health differs from retained weather acquisition.")
                expected_outcome = (
                    AttemptOutcome.SUCCEEDED
                    if weather["state"] == "OBSERVED" and typed_attempt.error_type is None
                    else AttemptOutcome.FAILED
                )
                expected_usability = (
                    AttemptUsability.USABLE
                    if weather["state"] == "OBSERVED"
                    and weather["cutoff_eligibility"] == "CUTOFF_VALID"
                    else AttemptUsability.UNUSABLE
                )
                if attempt_ref["digest"] != typed_attempt.digest or (
                    typed_attempt.fixture_id,
                    typed_attempt.fixture_revision_ref,
                    typed_attempt.fixture_revision_digest,
                    typed_attempt.cutoff_id,
                    typed_attempt.cutoff_digest,
                    typed_attempt.requested_scope_id,
                    typed_attempt.provider_health_digest,
                    typed_attempt.response_artifact_digest,
                    typed_attempt.response_digest,
                    typed_attempt.outcome,
                    typed_attempt.usability,
                ) != (
                    cutoff.fixture_id,
                    cutoff.fixture_revision_ref,
                    cutoff.fixture_revision_digest,
                    cutoff.cutoff_id,
                    cutoff.digest,
                    record.requested_scope.scope_id,
                    health_digest,
                    response_artifact_digest,
                    response_digest,
                    expected_outcome,
                    expected_usability,
                ):
                    raise F11Error("F12 attempt differs from its exact F07/F09/weather references.")

    def _verify_history(
        self,
        history: tuple[CanonicalFixture, ...],
        referenced: tuple[CanonicalFixture, ...],
        context: tuple[CanonicalFixture, ...],
    ) -> None:
        def facts(fixture: CanonicalFixture) -> bytes:
            value = fixture.to_dict()
            del value["provenance"]
            del value["cutoff_eligibility"]
            return _bytes(value)

        for fixture in history:
            matches = [item for item in referenced if facts(item) == facts(fixture)]
            if len(matches) != 1 or not set(fixture.provenance).issubset(matches[0].provenance):
                raise F11Error(
                    "Retained history differs from its exact fixture revision references."
                )
            row = (
                self.store._connection_for_repository()
                .execute(
                    """SELECT source_capture_id, observed_at_utc FROM fixture_revisions
                   WHERE revision_id = ? AND fixture_id = ?""",
                    (fixture.revision_id, fixture.fixture_id),
                )
                .fetchone()
            )
            if row is not None and not any(
                p.source_capture_id == str(row[0])
                and p.observed_at_utc == _canonical_utc(str(row[1]))
                for p in fixture.provenance
            ):
                raise F11Error(
                    "Retained canonical revision omitted its original source provenance."
                )
        for fixture in context:
            matches = [item for item in history if facts(item) == facts(fixture)]
            if len(matches) != 1 or not set(fixture.provenance).issubset(matches[0].provenance):
                raise F11Error("Retained history omitted exact requested context.")

    def _capture(
        self,
        capture_id: str | None,
        observed_at_utc: str,
        published_at_utc: str | None = None,
        *,
        verify_publication: bool = False,
    ) -> None:
        if capture_id is None:
            return
        row = (
            self.store._connection_for_repository()
            .execute(
                """SELECT content_sha256, artifact_digest, retrieved_at_utc,
                          source_published_at_utc
                   FROM source_captures WHERE capture_id = ?""",
                (capture_id,),
            )
            .fetchone()
        )
        if row is None or row[1] is None or row[0] != row[1]:
            raise F11Error("Source capture reference is missing or corrupt.")
        if datetime.fromisoformat(observed_at_utc) < datetime.fromisoformat(str(row[2])):
            raise F11Error("Source capture was retrieved after its claimed observation.")
        if row[3] is not None:
            published = datetime.fromisoformat(str(row[3]))
            if published > datetime.fromisoformat(observed_at_utc) or (
                verify_publication
                and (
                    published_at_utc is None
                    or datetime.fromisoformat(published_at_utc) != published
                )
            ):
                raise F11Error("Source capture publication reference differs.")
        self.artifacts.read_artifact(str(row[1]))

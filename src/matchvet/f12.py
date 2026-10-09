"""Immutable V2 contextual research attempts for the existing Open-Meteo path."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from matchvet.artifacts import ArtifactStore
from matchvet.match_evidence_cutoff import MatchEvidenceCutoff
from matchvet.matchweek_research import MatchweekResearchRepository, TrustedUTCClock
from matchvet.provider_health import (
    CapabilityCoverageEvidenceReference,
    OtherVersionedEvidenceReference,
    ProviderHealthRecord,
)
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import Store
from matchvet.weather import WeatherEvidence, WeatherRequest
from matchvet.weather_provider_health import (
    OPEN_METEO_PROVIDER_ID,
    WEATHER_CAPABILITY_ID,
    open_meteo_requested_scope,
)

F12_CONTRACT_VERSION = "matchvet-v2-contextual-research-attempt"
F12_SCHEMA_VERSION = 1
F12_ATTEMPT_MEDIA_TYPE = "application/vnd.matchvet.v2-contextual-attempt.v1+json"
CAUSAL_F12_CONTRACT_VERSION = "matchvet-causal-contextual-attempt-v2"
CAUSAL_F12_ATTEMPT_MEDIA_TYPE = "application/vnd.matchvet.causal-contextual-attempt.v2+json"
_RESPONSE_MEDIA_TYPE = "application/vnd.matchvet.f11-weather-response.v2+json"


class F12Error(ValueError):
    """An F12 attempt or one of its exact immutable references is invalid."""


class AttemptOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AttemptUsability(StrEnum):
    USABLE = "USABLE"
    UNUSABLE = "UNUSABLE"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ContextualResearchAttempt:
    """One immutable request, bound to one Open-Meteo capability and F07 cutoff."""

    contract_version: str
    schema_version: int
    attempt_id: str
    digest: str
    provider_id: str
    capability_id: str
    fixture_id: str
    fixture_revision_ref: str
    fixture_revision_digest: str
    cutoff_id: str
    cutoff_digest: str
    requested_scope_id: str
    outcome: AttemptOutcome
    usability: AttemptUsability
    acquired_at_utc: str
    retrieved_at_utc: str | None
    response_status: int | None
    error_type: str | None
    response_artifact_digest: str | None
    response_digest: str | None
    provider_health_digest: str
    candidate_contract_digest: str | None = None

    @classmethod
    def create(
        cls,
        *,
        cutoff: MatchEvidenceCutoff,
        request: WeatherRequest,
        weather: WeatherEvidence,
        health: ProviderHealthRecord,
        response_artifact_digest: str | None,
        error_type: str | None,
        response_status: int | None = None,
        candidate_contract_digest: str | None = None,
    ) -> ContextualResearchAttempt:
        scope = open_meteo_requested_scope(request)
        if (request.fixture_id, request.cutoff_utc) != (
            cutoff.fixture_id,
            cutoff.cutoff_at_utc,
        ):
            raise F12Error("Request differs from its exact F07 fixture cutoff.")
        if health.requested_scope != scope or (
            health.provider.provider_id,
            health.capability.capability_id,
        ) != (OPEN_METEO_PROVIDER_ID, WEATHER_CAPABILITY_ID):
            raise F12Error("F09 health differs from the exact Open-Meteo request scope.")
        if (weather.fixture_id, weather.cutoff_utc, weather.target_time_utc) != (
            request.fixture_id,
            request.cutoff_utc,
            request.target_time_utc,
        ):
            raise F12Error("Weather response differs from its exact fixture cutoff.")
        if weather.response_bytes is None and response_artifact_digest is not None:
            raise F12Error("Response artifact exists without captured weather response bytes.")
        if weather.response_bytes is not None and response_artifact_digest is None:
            raise F12Error("Captured weather response lacks its retained artifact reference.")

        outcome = (
            AttemptOutcome.SUCCEEDED
            if weather.state.value == "OBSERVED" and error_type is None
            else AttemptOutcome.FAILED
        )
        usability = (
            AttemptUsability.USABLE
            if weather.state.value == "OBSERVED"
            and (candidate_contract_digest is not None or weather.is_frozen_input)
            else AttemptUsability.UNUSABLE
        )
        acquired_at = health.checked_at_utc
        observed_status = (
            weather.response_status if weather.response_status is not None else response_status
        )
        identity = {
            "provider_id": OPEN_METEO_PROVIDER_ID,
            "capability_id": WEATHER_CAPABILITY_ID,
            "fixture_id": cutoff.fixture_id,
            "cutoff_id": cutoff.cutoff_id,
            "cutoff_digest": cutoff.digest,
            "requested_scope_id": scope.scope_id,
        }
        if candidate_contract_digest is not None:
            from matchvet.causal_candidate import require_digest

            require_digest(candidate_contract_digest)
            identity["candidate_contract_digest"] = candidate_contract_digest
        contract_version = (
            CAUSAL_F12_CONTRACT_VERSION
            if candidate_contract_digest is not None
            else F12_CONTRACT_VERSION
        )
        schema_version = 2 if candidate_contract_digest is not None else F12_SCHEMA_VERSION
        attempt_id = "f12:" + _sha256(_canonical_json(identity))
        payload: dict[str, Any] = {
            "contract_version": contract_version,
            "schema_version": schema_version,
            "attempt_id": attempt_id,
            **identity,
            "fixture_revision_ref": cutoff.fixture_revision_ref,
            "fixture_revision_digest": cutoff.fixture_revision_digest,
            "outcome": outcome.value,
            "usability": usability.value,
            "acquired_at_utc": acquired_at,
            "retrieved_at_utc": weather.retrieved_at_utc,
            "response_status": observed_status,
            "error_type": error_type,
            "response_artifact_digest": response_artifact_digest,
            "response_digest": weather.response_content_sha256,
            "provider_health_digest": health.digest,
        }
        digest = "sha256:" + _sha256(_canonical_json(payload))
        return cls(
            contract_version=contract_version,
            schema_version=schema_version,
            attempt_id=attempt_id,
            digest=digest,
            provider_id=OPEN_METEO_PROVIDER_ID,
            capability_id=WEATHER_CAPABILITY_ID,
            fixture_id=cutoff.fixture_id,
            fixture_revision_ref=cutoff.fixture_revision_ref,
            fixture_revision_digest=cutoff.fixture_revision_digest,
            cutoff_id=cutoff.cutoff_id,
            cutoff_digest=cutoff.digest,
            requested_scope_id=scope.scope_id,
            outcome=outcome,
            usability=usability,
            acquired_at_utc=acquired_at,
            retrieved_at_utc=weather.retrieved_at_utc,
            response_status=observed_status,
            error_type=error_type,
            response_artifact_digest=response_artifact_digest,
            response_digest=weather.response_content_sha256,
            provider_health_digest=health.digest,
            candidate_contract_digest=candidate_contract_digest,
        )

    def to_dict(self) -> dict[str, object]:
        result = {**asdict(self), "outcome": self.outcome.value, "usability": self.usability.value}
        if self.candidate_contract_digest is None:
            result.pop("candidate_contract_digest")
        return result

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_bytes(cls, encoded: bytes) -> ContextualResearchAttempt:
        try:
            value = json.loads(encoded)
            value["outcome"] = AttemptOutcome(value["outcome"])
            value["usability"] = AttemptUsability(value["usability"])
            attempt = cls(**value)
        except (KeyError, TypeError, ValueError) as error:
            raise F12Error("Malformed contextual research attempt.") from error
        if (
            attempt.to_bytes() != encoded
            or (attempt.contract_version, attempt.schema_version)
            != (
                (CAUSAL_F12_CONTRACT_VERSION, 2)
                if attempt.candidate_contract_digest is not None
                else (F12_CONTRACT_VERSION, F12_SCHEMA_VERSION)
            )
            or type(attempt.schema_version) is not int
            or attempt.provider_id != OPEN_METEO_PROVIDER_ID
            or attempt.capability_id != WEATHER_CAPABILITY_ID
        ):
            raise F12Error("Noncanonical or unsupported contextual research attempt.")
        payload = attempt.to_dict()
        payload.pop("digest")
        identity = {
            "provider_id": attempt.provider_id,
            "capability_id": attempt.capability_id,
            "fixture_id": attempt.fixture_id,
            "cutoff_id": attempt.cutoff_id,
            "cutoff_digest": attempt.cutoff_digest,
            "requested_scope_id": attempt.requested_scope_id,
        }
        if attempt.candidate_contract_digest is not None:
            from matchvet.causal_candidate import require_digest

            require_digest(attempt.candidate_contract_digest)
            identity["candidate_contract_digest"] = attempt.candidate_contract_digest
        if attempt.attempt_id != "f12:" + _sha256(_canonical_json(identity)):
            raise F12Error("Contextual research attempt ID differs from its request identity.")
        if attempt.digest != "sha256:" + _sha256(_canonical_json(payload)):
            raise F12Error("Contextual research attempt digest differs from its bytes.")
        return attempt


class ContextualAttemptRepository:
    """Publish and resolve exact F12 attempts as protected immutable artifacts."""

    def __init__(
        self,
        store: Store,
        *,
        clock: TrustedUTCClock | None = None,
        candidate_contract_digest: str | None = None,
        selection_contract: str | None = None,
    ) -> None:
        self.artifacts = ArtifactStore(store)
        self.research = MatchweekResearchRepository(
            store,
            clock=clock,
            candidate_contract_digest=candidate_contract_digest,
            selection_contract=selection_contract,
        )
        self._clock = clock
        self.store = store
        self.candidate_contract_digest = candidate_contract_digest
        self.attempt_media_type = (
            CAUSAL_F12_ATTEMPT_MEDIA_TYPE
            if candidate_contract_digest is not None
            else F12_ATTEMPT_MEDIA_TYPE
        )

    def publish(self, attempt: ContextualResearchAttempt) -> ContextualResearchAttempt:
        if attempt.candidate_contract_digest != self.candidate_contract_digest:
            raise F12Error(
                "Attempt candidate descriptor differs from explicit constructor context."
            )
        checked = ContextualResearchAttempt.from_bytes(attempt.to_bytes())
        from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository

        cutoff = MatchEvidenceCutoffRepository(self.store).get_by_id(checked.cutoff_id)
        if cutoff is None:
            raise F12Error("Exact F07 cutoff is missing.")
        self.research.validate_context(cutoff.freeze_id, cutoff.policy_digest)
        selected = self.research.selected_for_boundary(cutoff.freeze_id, cutoff.policy_digest)
        if selected is not None:
            manifest = self.artifacts.verify_manifest(selected.digest)
            digest = _sha256(checked.to_bytes())
            if not any(ref.digest == digest for ref in manifest.artifacts):
                raise F12Error("Attempt differs from the exact selected references.")
            value = json.loads(self.artifacts.read_artifact(selected.f16_manifest_digest))
            rows = [row for row in value["matches"] if row["cutoff_id"] == checked.cutoff_id]
            if len(rows) != 1:
                raise F12Error("Attempt differs from the exact selected cutoff.")
            evidence = json.loads(self.artifacts.read_artifact(rows[0]["evidence_digest"]))
            matches = [
                row
                for row in evidence["matches"]
                if row["cutoff"]["cutoff_id"] == checked.cutoff_id
            ]
            if len(matches) != 1 or matches[0]["contextual_attempt"] != {
                "attempt_id": checked.attempt_id,
                "digest": checked.digest,
            }:
                raise F12Error("Attempt differs from the exact selected F11 reference.")
            selected_attempt = self.get(checked.attempt_id, cutoff_id=checked.cutoff_id)
            if selected_attempt.to_bytes() != checked.to_bytes():
                raise F12Error("Attempt differs from the exact selected acquisition.")
            return selected_attempt
        self.research.require_candidate_write(cutoff.freeze_id, cutoff.policy_digest)
        if self.candidate_contract_digest is None and self.research.is_corrected(
            cutoff.policy_digest
        ):
            boundary = datetime.fromisoformat(cutoff.cutoff_at_utc)
            if any(
                datetime.fromisoformat(time) > boundary
                for time in (checked.acquired_at_utc, checked.retrieved_at_utc)
                if time is not None
            ):
                raise F12Error("Attempt acquisition or retrieval is after the common cutoff.")

        def require_first_attempt() -> None:
            for metadata in self.store.artifact_catalog():
                if metadata.media_type == self.attempt_media_type:
                    prior = ContextualResearchAttempt.from_bytes(
                        self.artifacts.read_artifact(metadata.digest)
                    )
                    if (
                        prior.cutoff_id == checked.cutoff_id
                        and prior.to_bytes() != checked.to_bytes()
                    ):
                        raise F12Error("A frozen attempt already exists for this exact cutoff.")

        artifacts = self.research.candidate_artifacts(
            cutoff.freeze_id, cutoff.policy_digest, check_state=require_first_attempt
        )
        if self.research.is_corrected(cutoff.policy_digest):
            require_first_attempt()
        existing = self._get_optional(checked.attempt_id)
        if existing is not None:
            if existing.to_bytes() != checked.to_bytes():
                raise F12Error("A different acquisition already exists for this exact request.")
            self.research.require_candidate_write(cutoff.freeze_id, cutoff.policy_digest)
            return existing
        from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository

        cutoff = MatchEvidenceCutoffRepository(self.store).get_by_id(checked.cutoff_id)
        health = ProviderHealthRepository(self.store).get(checked.provider_health_digest)
        if cutoff is None or (
            cutoff.fixture_id,
            cutoff.digest,
            cutoff.fixture_revision_ref,
            cutoff.fixture_revision_digest,
        ) != (
            checked.fixture_id,
            checked.cutoff_digest,
            checked.fixture_revision_ref,
            checked.fixture_revision_digest,
        ):
            raise F12Error("Attempt differs from its exact F07 cutoff.")
        if health is None or health.digest != checked.provider_health_digest:
            raise F12Error("Attempt names a missing exact F09 health record.")
        if health.requested_scope.scope_id != checked.requested_scope_id:
            raise F12Error("Attempt and F09 health requested scopes differ.")
        if health.checked_at_utc != checked.acquired_at_utc or (
            health.provider.provider_id,
            health.capability.capability_id,
        ) != (checked.provider_id, checked.capability_id):
            raise F12Error("Attempt acquisition identity differs from its exact F09 record.")
        event = {
            "request_scope_id": checked.requested_scope_id,
            "checked_at_utc": health.checked_at_utc,
            "response_digest": checked.response_digest,
            "response_status": checked.response_status,
            "retrieved_at_utc": checked.retrieved_at_utc,
            "error_type": checked.error_type,
        }
        event_digest = "sha256:" + _sha256(_canonical_json(event))
        event_references = [
            reference
            for reference in health.provenance
            if isinstance(reference, OtherVersionedEvidenceReference)
        ]
        coverage_references = [
            reference
            for reference in health.provenance
            if isinstance(reference, CapabilityCoverageEvidenceReference)
        ]
        if len(event_references) != 1 or event_references[0].digest != event_digest:
            raise F12Error("Attempt differs from the exact F09 acquisition event.")
        if any(reference.digest != checked.response_digest for reference in coverage_references):
            raise F12Error("Attempt and F09 response references differ.")
        if checked.outcome is AttemptOutcome.SUCCEEDED and (
            checked.response_artifact_digest is None
            or checked.response_digest is None
            or checked.usability is not AttemptUsability.USABLE
        ):
            raise F12Error("A successful attempt requires a captured usable response.")
        if (
            checked.outcome is AttemptOutcome.FAILED
            and checked.usability is AttemptUsability.USABLE
        ):
            raise F12Error("A failed attempt cannot be marked usable.")
        self._validate_response(checked)
        if self.candidate_contract_digest is not None:
            from matchvet.candidate_primitives import retain_health

            retain_health(self.store, artifacts, checked.provider_health_digest)
        artifacts.publish_artifact(checked.to_bytes(), self.attempt_media_type)
        self.research.require_candidate_write(cutoff.freeze_id, cutoff.policy_digest)
        return checked

    def get(self, attempt_id: str, *, cutoff_id: str | None = None) -> ContextualResearchAttempt:
        scope = self.store._artifact_catalog_scope
        if scope is None and cutoff_id is not None:
            from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository

            cutoff = MatchEvidenceCutoffRepository(self.store).get_by_id(cutoff_id)
            if cutoff is None:
                raise F12Error("Exact F07 cutoff is missing.")
            scope = self.research.indexed_replay_catalog(cutoff.freeze_id, cutoff.policy_digest)
        with self.store._scope_artifact_catalog(scope):
            attempt = self._get_optional(attempt_id)
        if attempt is None:
            raise F12Error("Exact contextual research attempt is missing.")
        if cutoff_id is not None and attempt.cutoff_id != cutoff_id:
            raise F12Error("Attempt differs from the exact requested cutoff.")
        return attempt

    def _get_optional(self, attempt_id: str) -> ContextualResearchAttempt | None:
        matches: list[ContextualResearchAttempt] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type not in {F12_ATTEMPT_MEDIA_TYPE, CAUSAL_F12_ATTEMPT_MEDIA_TYPE}:
                continue
            encoded = self.artifacts.read_artifact(metadata.digest)
            attempt = ContextualResearchAttempt.from_bytes(encoded)
            expected_media = (
                CAUSAL_F12_ATTEMPT_MEDIA_TYPE
                if attempt.candidate_contract_digest is not None
                else F12_ATTEMPT_MEDIA_TYPE
            )
            if metadata.media_type != expected_media:
                raise F12Error("Attempt schema/media dispatch differs.")
            if attempt.attempt_id == attempt_id:
                if metadata.retention_class != "PROTECTED":
                    raise F12Error("Attempt artifact is not protected.")
                matches.append(attempt)
        if len({attempt.digest for attempt in matches}) > 1:
            raise F12Error("Conflicting attempts share one exact request identity.")
        return matches[0] if matches else None

    def find_for_request(
        self, *, fixture_id: str, cutoff_id: str, cutoff_digest: str, requested_scope_id: str
    ) -> ContextualResearchAttempt | None:
        identity = {
            "provider_id": OPEN_METEO_PROVIDER_ID,
            "capability_id": WEATHER_CAPABILITY_ID,
            "fixture_id": fixture_id,
            "cutoff_id": cutoff_id,
            "cutoff_digest": cutoff_digest,
            "requested_scope_id": requested_scope_id,
        }
        from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository

        cutoff = MatchEvidenceCutoffRepository(self.store).replay(cutoff_id)
        self.research.validate_context(cutoff.freeze_id, cutoff.policy_digest)
        if self.candidate_contract_digest is not None:
            selected = self.research.selected_for_boundary(cutoff.freeze_id, cutoff.policy_digest)
            if selected is None:
                self.research.require_candidate_write(cutoff.freeze_id, cutoff.policy_digest)
            identity["candidate_contract_digest"] = self.candidate_contract_digest
        attempt_id = "f12:" + _sha256(_canonical_json(identity))
        scope = self.research.indexed_replay_catalog(cutoff.freeze_id, cutoff.policy_digest)
        with self.store._scope_artifact_catalog(scope):
            result = self._get_optional(attempt_id)
        if self.candidate_contract_digest is not None and selected is None:
            self.research.require_candidate_write(cutoff.freeze_id, cutoff.policy_digest)
        return result

    def _validate_response(self, attempt: ContextualResearchAttempt) -> None:
        response_ref = attempt.response_artifact_digest
        if response_ref is None:
            if attempt.response_digest is not None:
                raise F12Error("Attempt response digest has no response artifact reference.")
            return
        metadata = self.store.artifact_metadata(response_ref)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            _RESPONSE_MEDIA_TYPE,
            "PROTECTED",
        ):
            raise F12Error("Attempt response artifact is missing or not protected.")
        try:
            encoded = self.artifacts.read_artifact(response_ref)
            envelope = json.loads(encoded)
            content = base64.b64decode(envelope["body_base64"], validate=True)
        except (KeyError, ValueError, TypeError) as error:
            raise F12Error("Attempt response artifact is malformed.") from error
        if (
            _canonical_json(envelope) != encoded
            or set(envelope) != {"schema_version", "response_content_sha256", "body_base64"}
            or type(envelope["schema_version"]) is not int
            or envelope["schema_version"] != 2
            or envelope.get("response_content_sha256") != attempt.response_digest
            or _sha256(content) != attempt.response_digest
        ):
            raise F12Error("Attempt and retained response digests differ.")

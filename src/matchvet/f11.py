"""F06/F07-native immutable workload and weather research evidence.

The first build retains acquisition for an exact request. Retries replay that
artifact, including F09 observations, without observing a new provider state.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from datetime import datetime

from matchvet.artifacts import ArtifactStore
from matchvet.evidence import CutoffEligibility
from matchvet.f11_contracts import (
    CAUSAL_EVIDENCE_MEDIA_TYPE as CAUSAL_EVIDENCE_MEDIA_TYPE,
)
from matchvet.f11_contracts import (
    CAUSAL_HISTORY_MEDIA_TYPE as CAUSAL_HISTORY_MEDIA_TYPE,
)
from matchvet.f11_contracts import (
    EVIDENCE_MEDIA_TYPE as EVIDENCE_MEDIA_TYPE,
)
from matchvet.f11_contracts import (
    HISTORY_MEDIA_TYPE as HISTORY_MEDIA_TYPE,
)
from matchvet.f11_contracts import (
    RESPONSE_MEDIA_TYPE as RESPONSE_MEDIA_TYPE,
)
from matchvet.f11_contracts import (
    F11Error as F11Error,
)
from matchvet.f11_contracts import (
    F11EvidenceSet as F11EvidenceSet,
)
from matchvet.f11_contracts import (
    _AcquisitionClient,
    _parse_error_type,
    _RetainedWeatherClient,
)
from matchvet.f11_contracts import (
    _at_cutoff as _at_cutoff,
)
from matchvet.f11_contracts import (
    _bytes as _bytes,
)
from matchvet.f11_contracts import (
    _digest as _digest,
)
from matchvet.f11_contracts import (
    _history_values as _history_values,
)
from matchvet.f11_contracts import (
    prospective_context as prospective_context,
)
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
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import MatchweekResearchRepository, TrustedUTCClock
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
    WeatherRequest,
    WeatherTarget,
    _build_weather_evidence,
)
from matchvet.weather_provider_health import open_meteo_requested_scope
from matchvet.workload import (
    CanonicalFixture,
    WorkloadCalculator,
    WorkloadRules,
    _canonical_utc,
    load_canonical_fixture_history,
)


class F11EvidenceRepository:
    """Own exact joins, acquisition retention and verified evidence-set replay."""

    def __init__(
        self,
        store: Store,
        *,
        clock: TrustedUTCClock | None = None,
        candidate_contract_digest: str | None = None,
        selection_contract: str | None = None,
    ) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)
        self.research = MatchweekResearchRepository(
            store,
            clock=clock,
            candidate_contract_digest=candidate_contract_digest,
            selection_contract=selection_contract,
        )
        self._clock = clock
        self.candidate_contract_digest = candidate_contract_digest
        self.evidence_media_type = (
            CAUSAL_EVIDENCE_MEDIA_TYPE
            if candidate_contract_digest is not None
            else EVIDENCE_MEDIA_TYPE
        )

    def build_or_replay_for_freeze(self, freeze_id: str, policy_digest: str) -> F11EvidenceSet:
        """Reuse the sole retained evidence request for these exact F06/F07 inputs.

        F15 does not carry provider or venue configuration. A previously retained
        exact set therefore supplies it; ambiguity is rejected instead of choosing
        a latest or fixture-only variant. With no retained set, acquire without
        weather because no exact venue mapping is available at this boundary.
        """
        self.research.validate_context(freeze_id, policy_digest)
        selected = self.research.selected_for_boundary(freeze_id, policy_digest)
        if selected is not None:
            from matchvet.f16 import F16MatchweekProcessor

            manifest = F16MatchweekProcessor(self.store).replay_manifest(
                selected.f16_manifest_digest
            )
            return self.replay(
                manifest.match_results[0].evidence_digest,
                freeze_id=freeze_id,
                policy_digest=policy_digest,
            )
        self.research.require_candidate_write(freeze_id, policy_digest)
        retained: set[str] = set()
        for metadata in self.store.artifact_catalog():
            if metadata.media_type != self.evidence_media_type:
                continue
            value = self._read(metadata.digest, self.evidence_media_type)
            payload = json.loads(value)
            if (payload.get("freeze_id"), payload.get("policy_digest")) == (
                freeze_id,
                policy_digest,
            ):
                retained.add(metadata.digest)
        if len(retained) > 1:
            raise F11Error("Conflicting F11 evidence sets name the same exact F06/F07 inputs.")
        if retained:
            evidence = self.replay(
                next(iter(retained)), freeze_id=freeze_id, policy_digest=policy_digest
            )
            self.research.require_candidate_write(freeze_id, policy_digest)
            return evidence
        return self.build(freeze_id, policy_digest, weather_client=None)

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
        self.research.validate_context(freeze_id, policy_digest)
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
        if self.candidate_contract_digest is not None:
            request["candidate_contract_digest"] = self.candidate_contract_digest
        request_digest = _digest(_bytes(request))
        self.research.validate_context(freeze_id, policy_digest)
        selected = self.research.selected_for_boundary(freeze_id, policy_digest)
        if selected is not None:
            from matchvet.f16 import F16MatchweekProcessor

            manifest = F16MatchweekProcessor(self.store).replay_manifest(
                selected.f16_manifest_digest
            )
            evidence = self.replay(
                manifest.match_results[0].evidence_digest,
                freeze_id=freeze_id,
                policy_digest=policy_digest,
            )
            if evidence.to_dict()["request_digest"] != request_digest:
                raise F11Error("The selected frozen F11 request cannot change.")
            return evidence
        self.research.require_candidate_write(freeze_id, policy_digest)
        corrected = self.research.is_corrected(policy_digest)
        existing: list[F11EvidenceSet] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type == self.evidence_media_type:
                value = self._read(metadata.digest, self.evidence_media_type)
                candidate = json.loads(value)
                if (
                    corrected
                    and (candidate["freeze_id"], candidate["policy_digest"])
                    == (freeze_id, policy_digest)
                    and candidate["request_digest"] != request_digest
                ):
                    raise F11Error("The frozen F11 request cannot change.")
                if candidate["request_digest"] == request_digest:
                    existing.append(
                        self.replay(
                            metadata.digest, freeze_id=freeze_id, policy_digest=policy_digest
                        )
                    )
        if len(existing) > 1:
            raise F11Error("Conflicting evidence sets name the same exact request.")
        if existing:
            self.research.require_candidate_write(freeze_id, policy_digest)
            return existing[0]
        expected_evidence_digest: str | None = None

        def require_exact_request() -> None:
            for metadata in self.store.artifact_catalog():
                if metadata.media_type != self.evidence_media_type:
                    continue
                prior = json.loads(self._read(metadata.digest, self.evidence_media_type))
                if (prior["freeze_id"], prior["policy_digest"]) == (freeze_id, policy_digest) and (
                    prior["request_digest"] != request_digest
                    or (
                        expected_evidence_digest is not None
                        and metadata.digest != expected_evidence_digest
                    )
                ):
                    raise F11Error("The frozen F11 request or evidence cannot change.")

        artifacts = self.research.candidate_artifacts(
            freeze_id,
            policy_digest,
            check_state=require_exact_request if corrected else None,
        )
        if not corrected and self.candidate_contract_digest is None:
            # Keep the historical publication seam while guarding its transactions.
            self.artifacts._write_guard = artifacts._write_guard
            artifacts = self.artifacts
        history = load_canonical_fixture_history(
            self.store, season=freeze.season, context_fixtures=context
        )
        if corrected:
            boundary = datetime.fromisoformat(cutoffs[0].cutoff_at_utc)
            frozen_history = []
            for fixture in history:
                provenance = tuple(
                    item
                    for item in fixture.provenance
                    if datetime.fromisoformat(item.observed_at_utc) <= boundary
                    and (
                        item.published_at_utc is None
                        or datetime.fromisoformat(item.published_at_utc)
                        <= datetime.fromisoformat(item.observed_at_utc)
                    )
                )
                if provenance:
                    frozen_history.append(replace(fixture, provenance=provenance))
            history = tuple(frozen_history)
        history_bytes = _bytes(sorted((f.to_dict() for f in history), key=_bytes))
        history_media = HISTORY_MEDIA_TYPE
        if self.candidate_contract_digest is not None:
            history_bytes = _bytes(
                {
                    "schema_version": 1,
                    "candidate_contract_digest": self.candidate_contract_digest,
                    "freeze_id": freeze_id,
                    "policy_digest": policy_digest,
                    "history": json.loads(history_bytes),
                }
            )
            history_media = CAUSAL_HISTORY_MEDIA_TYPE
        history_digest = artifacts.publish_artifact(history_bytes, history_media).digest
        matches = []
        contextual_attempts = ContextualAttemptRepository(
            self.store, clock=self._clock, candidate_contract_digest=self.candidate_contract_digest
        )
        for cutoff in cutoffs:
            self.research.require_candidate_write(freeze_id, policy_digest)
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
                _AcquisitionClient(
                    weather_client,
                    (lambda: self.research.require_candidate_write(freeze_id, policy_digest)),
                    causal=self.candidate_contract_digest is not None,
                    enforce_cutoff=corrected,
                )
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
                builder = WeatherEvidenceBuilder(
                    replay_client,
                    candidate_contract_digest=self.candidate_contract_digest,
                    store=self.store,
                )
            else:
                builder = WeatherEvidenceBuilder(
                    acquisition,
                    candidate_contract_digest=self.candidate_contract_digest,
                    provider_health_repository=ProviderHealthRepository(
                        self.store,
                        write_guard=(
                            lambda: self.research.require_candidate_write(freeze_id, policy_digest)
                        ),
                    ),
                    health_clock=(
                        lambda: self.research.require_preselection_open(freeze_id, policy_digest)
                    )
                    if corrected and self.candidate_contract_digest is None
                    else None,
                    admission_guard=(
                        lambda: self.research.require_candidate_write(freeze_id, policy_digest)
                    ),
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
            if (
                corrected
                and self.candidate_contract_digest is None
                and weather.forecast_issue_time_source == "retrieval_time_bound"
            ):
                raise F11Error(
                    "Corrected weather requires a known publication time before retrieval."
                )
            if (
                corrected
                and weather.forecast_issue_time_utc is not None
                and (
                    weather.retrieved_at_utc is None
                    or datetime.fromisoformat(weather.forecast_issue_time_utc)
                    > datetime.fromisoformat(weather.retrieved_at_utc)
                )
            ):
                raise F11Error("Weather publication is after its retrieval.")
            error_type = (
                retained_attempt.error_type
                if retained_attempt is not None
                else acquisition.error_type
                if acquisition
                else None
            )
            response_digest = None
            if weather.response_bytes is not None:
                response_digest = artifacts.publish_artifact(
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
                        causal=self.candidate_contract_digest is not None,
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
                        candidate_contract_digest=self.candidate_contract_digest,
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
                    "workload": prospective_context(workload.to_dict())
                    if self.candidate_contract_digest is not None
                    else workload.to_dict(),
                    "weather": prospective_context(weather.to_dict())
                    if self.candidate_contract_digest is not None
                    else weather.to_dict(),
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
        if self.candidate_contract_digest is not None:
            payload.update(
                schema_version=4,
                candidate_contract_digest=self.candidate_contract_digest,
                qualification="UNQUALIFIED",
            )
        evidence = F11EvidenceSet(_bytes(payload))
        expected_evidence_digest = evidence.digest
        # Validate all references before publication, including caller context.
        self._validate(evidence, freeze_id, policy_digest)
        artifacts.publish_artifact(evidence.to_bytes(), self.evidence_media_type)
        result = self.replay(evidence.digest, freeze_id=freeze_id, policy_digest=policy_digest)
        self.research.require_candidate_write(freeze_id, policy_digest)
        return result

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
        supported = {media_type}
        if media_type == EVIDENCE_MEDIA_TYPE:
            supported.add(CAUSAL_EVIDENCE_MEDIA_TYPE)
        if (
            metadata is None
            or metadata.media_type not in supported
            or metadata.retention_class != "PROTECTED"
        ):
            raise F11Error("Missing or wrong F11 artifact reference.")
        content = self.artifacts.read_artifact(digest)
        if media_type == EVIDENCE_MEDIA_TYPE:
            try:
                value = json.loads(content)
                expected = 4 if metadata.media_type == CAUSAL_EVIDENCE_MEDIA_TYPE else 3
                if type(value["schema_version"]) is not int or value["schema_version"] != expected:
                    raise F11Error("F11 evidence media/schema identity differs.")
            except F11Error:
                raise
            except (ValueError, TypeError, KeyError) as error:
                raise F11Error("Malformed F11 evidence contract.") from error
        return content

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
        causal = value.get("schema_version") == 4
        candidate_digest = value.get("candidate_contract_digest") if causal else None
        if causal:
            if not isinstance(candidate_digest, str):
                raise F11Error("Explicit candidate descriptor is missing.")
            candidate = self.research.resolve_candidate(candidate_digest)
            if (candidate.freeze_id, candidate.cutoff_policy_digest) != (
                freeze_id,
                policy_digest,
            ) or value.get("qualification") != "UNQUALIFIED":
                raise F11Error("F11 candidate descriptor context differs.")
        if (
            _bytes(value) != evidence.to_bytes()
            or set(value)
            != ({"candidate_contract_digest", "qualification"} if causal else set())
            | {
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
            or value["schema_version"] != (4 if causal else 3)
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
        if request.get("candidate_contract_digest") != candidate_digest:
            raise F11Error("F11 request candidate identity differs.")
        rule_values = dict(request["rules"])
        rule_values["recent_windows_days"] = tuple(rule_values["recent_windows_days"])
        rules = WorkloadRules(**rule_values)
        history_content = self._read(
            value["history_artifact_digest"],
            CAUSAL_HISTORY_MEDIA_TYPE if causal else HISTORY_MEDIA_TYPE,
        )
        if causal:
            envelope = json.loads(history_content)
            if set(envelope) != {
                "schema_version",
                "candidate_contract_digest",
                "freeze_id",
                "policy_digest",
                "history",
            } or envelope != {
                "schema_version": 1,
                "candidate_contract_digest": candidate_digest,
                "freeze_id": freeze_id,
                "policy_digest": policy_digest,
                "history": envelope["history"],
            }:
                raise F11Error("F11 history candidate association differs.")
            history_content = _bytes(envelope["history"])
        history = _history_values(history_content)
        context = _history_values(_bytes(request["context"]))
        referenced_history = load_canonical_fixture_history(
            self.store,
            season=freeze.season,
            context_fixtures=context,
            exact_revisions=frozenset(
                (f.fixture_id, f.revision_id, f.revision_digest) for f in history
            )
            if causal
            else None,
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
            expected_workload = (
                prospective_context(workload.to_dict()) if causal else workload.to_dict()
            )
            if match["workload"] != json.loads(_bytes(expected_workload)):
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
            # Reader-only retained bytes cannot acquire or persist health metadata.
            expected = _build_weather_evidence(
                fixture_id=cutoff.fixture_id,
                target_time_utc=target.kickoff_utc or "",
                cutoff_utc=cutoff.cutoff_at_utc,
                location=location,
                client=retained_client,
                selection_contract="matchvet-causal-selection-v2"
                if causal
                else "postcommit-upper-bound-v1",
            )
            if weather != (
                prospective_context(expected.to_dict()) if causal else expected.to_dict()
            ):
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
                if causal:
                    from matchvet.candidate_primitives import verify_health

                    verify_health(self.store, health_digest)
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
                        attempt_ref["attempt_id"], cutoff_id=cutoff.cutoff_id
                    )
                except F12Error as error:
                    raise F11Error("F12 attempt artifact is missing or corrupt.") from error
                if (
                    attempt_ref["digest"] != typed_attempt.digest
                    or typed_attempt.candidate_contract_digest != candidate_digest
                ):
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
                            causal=causal,
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
                    and (causal or weather["cutoff_eligibility"] == "CUTOFF_VALID")
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

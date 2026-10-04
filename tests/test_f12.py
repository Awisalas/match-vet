from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from test_match_evidence_cutoff import _freeze

from matchvet.f11 import F11EvidenceRepository
from matchvet.f12 import (
    ContextualAttemptRepository,
    ContextualResearchAttempt,
    F12Error,
)
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import open_store
from matchvet.weather import (
    StaticWeatherClient,
    VenueLocation,
    WeatherRequest,
    parse_open_meteo_response,
)
from matchvet.workload import load_canonical_fixture_history


def _repack(
    attempt: ContextualResearchAttempt, **changes: str | int | None
) -> ContextualResearchAttempt:
    """Build a self-consistent changed value to exercise repository reference checks."""
    value = attempt.to_dict()
    value.update(changes)
    identity = {
        "provider_id": value["provider_id"],
        "capability_id": value["capability_id"],
        "fixture_id": value["fixture_id"],
        "cutoff_id": value["cutoff_id"],
        "cutoff_digest": value["cutoff_digest"],
        "requested_scope_id": value["requested_scope_id"],
    }
    value["attempt_id"] = "f12:" + hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    value.pop("digest")
    value["digest"] = "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()
    return ContextualResearchAttempt.from_bytes(canonical_json(value).encode())


def test_f12_attempt_bytes_are_deterministic_and_references_fail_closed(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy_digest = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy_digest)[0]
        target = load_canonical_fixture_history(store)[0]
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        request = WeatherRequest(
            target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
        )
        client = StaticWeatherClient(
            {
                request.url: {
                    "latitude": 6.5,
                    "longitude": 3.4,
                    "forecast_issue_time": "2026-09-25T10:00:00Z",
                    "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
                }
            },
            retrieved_at_utc="2026-09-25T12:00:00Z",
        )
        evidence = F11EvidenceRepository(store).build(
            freeze_id, policy_digest, weather_client=client, locations={target.fixture_id: location}
        )
        row = evidence.to_dict()["matches"][0]
        reference = row["contextual_attempt"]
        repository = ContextualAttemptRepository(store)
        attempt = repository.get(reference["attempt_id"])
        health = ProviderHealthRepository(store).get(attempt.provider_health_digest)
        assert health is not None

        artifacts = repository.artifacts
        assert attempt.response_artifact_digest is not None
        envelope = json.loads(artifacts.read_artifact(attempt.response_artifact_digest))

        content = base64.b64decode(envelope["body_base64"], validate=True)
        weather = parse_open_meteo_response(
            content,
            request,
            retrieved_at_utc=attempt.retrieved_at_utc or "",
            response_status=attempt.response_status or 200,
        )
        independently_created = ContextualResearchAttempt.create(
            cutoff=cutoff,
            request=request,
            weather=weather,
            health=health,
            response_artifact_digest=attempt.response_artifact_digest,
            error_type=attempt.error_type,
            response_status=attempt.response_status,
        )
        assert independently_created.to_bytes() == attempt.to_bytes()
        assert independently_created.digest == attempt.digest
        digest_payload = attempt.to_dict()
        digest_payload.pop("digest")
        assert (
            attempt.digest
            == "sha256:" + hashlib.sha256(canonical_json(digest_payload).encode()).hexdigest()
        )

        bad_references = (
            _repack(attempt, fixture_id="other-fixture"),
            _repack(attempt, cutoff_id="f07:" + "0" * 64),
            _repack(attempt, requested_scope_id="sha256:" + "0" * 64),
            _repack(attempt, response_artifact_digest="0" * 64),
            _repack(attempt, provider_health_digest="sha256:" + "0" * 64),
        )
        for bad_attempt in bad_references:
            with pytest.raises(F12Error):
                repository.publish(bad_attempt)

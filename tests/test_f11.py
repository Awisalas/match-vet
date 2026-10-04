from dataclasses import asdict
from pathlib import Path

import pytest
from test_match_evidence_cutoff import _freeze

from matchvet.f11 import F11EvidenceRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.store import open_store


def test_exact_f06_f07_evidence_is_immutable_and_replays(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
        repo = F11EvidenceRepository(store)
        evidence = repo.build(freeze_id, policy, weather_client=None)
        match = evidence.to_dict()["matches"][0]
        assert match["cutoff"] == {
            **asdict(cutoff),
            "cutoff_id": cutoff.cutoff_id,
            "digest": cutoff.digest,
        }
        assert match["workload"]["cutoff_utc"] == "2026-09-25T18:00:00.000000+00:00"
        assert match["weather"]["state"] == "UNKNOWN"
        assert match["contextual_attempt"] is None
        assert repo.replay(evidence.digest, freeze_id=freeze_id, policy_digest=policy) == evidence
        assert repo.build(freeze_id, policy, weather_client=None).to_bytes() == evidence.to_bytes()


def test_replay_refuses_weather_that_disagrees_with_retained_response(tmp_path: Path) -> None:
    import json

    import pytest

    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, F11Error
    from matchvet.matchweek_membership import canonical_json
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
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
        repo = F11EvidenceRepository(store)
        result = repo.build(
            freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
        )
        assert result.to_dict()["matches"][0]["weather"]["state"] == "OBSERVED"
        forged = json.loads(result.to_bytes())
        forged["matches"][0]["weather"]["values"]["temperature_2m"] = 99
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F11Error, match="Weather"):
            repo.replay(digest, freeze_id=freeze_id, policy_digest=policy)


def test_friday_and_monday_use_separate_workload_and_weather_boundaries(tmp_path: Path) -> None:
    from test_matchweek_membership import _persistable_schedule_assessment

    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import (
        CanonicalFixture,
        FixtureProvenance,
        load_canonical_fixture_history,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (
                ("2026-09-25", "20:00", "Shared United", "Shared City"),
                ("2026-09-28", "20:00", "Shared United", "Monday City"),
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, policy)
        history = load_canonical_fixture_history(store)
        team = history[0].home_team_id
        context = tuple(
            CanonicalFixture(
                fixture_id=name,
                home_team_id=team,
                away_team_id="context-opponent",
                kickoff_utc=kickoff,
                competition_key="cup",
                competition_name="Cup",
                competition_type="DOMESTIC_CUP",
                season="2026-27",
                status="COMPLETED",
                revision_id=name,
                revision_digest=name,
                provenance=(FixtureProvenance("cup", "https://cup.test", learned, learned),),
                cutoff_eligibility="CUTOFF_VALID",
            )
            for name, kickoff, learned in (
                ("pre", "2026-09-22T19:00:00Z", "2026-09-24T12:00:00Z"),
                ("late", "2026-09-23T19:00:00Z", "2026-09-26T12:00:00Z"),
                ("published-late", "2026-09-21T19:00:00Z", "2026-09-29T12:00:00Z"),
            )
        )
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        responses = {}
        for cutoff in boundaries:
            target = next(f for f in history if f.fixture_id == cutoff.fixture_id)
            request = WeatherRequest(
                target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
            )
            responses[request.url] = {
                "latitude": 6.5,
                "longitude": 3.4,
                "forecast_issue_time": "2026-09-26T10:00:00Z",
                "hourly": {
                    "time": [request.interval_start_utc],
                    **{variable: [27] for variable in request.variables},
                },
            }
        client = StaticWeatherClient(responses, retrieved_at_utc="2026-09-26T12:00:00Z")
        repo = F11EvidenceRepository(store)
        locations = {f.fixture_id: location for f in history}
        result = repo.build(
            freeze.freeze_id,
            policy,
            weather_client=client,
            context_fixtures=context,
            locations=locations,
        )
        matches = sorted(result.to_dict()["matches"], key=lambda m: m["cutoff"]["cutoff_at_utc"])
        friday, monday = matches
        assert friday["cutoff"]["cutoff_at_utc"] == "2026-09-25T18:00:00.000000+00:00"
        assert monday["cutoff"]["cutoff_at_utc"] == "2026-09-28T18:00:00.000000+00:00"
        assert friday["workload"]["home"]["cross_competition_fixture_ids"] == ["pre"]
        assert set(monday["workload"]["home"]["cross_competition_fixture_ids"]) == {"pre", "late"}
        assert friday["weather"]["state"] == "UNKNOWN"
        assert friday["weather"]["unknown_reason"] == "FORECAST_POST_CUTOFF"
        assert monday["weather"]["state"] == "OBSERVED"
        for match in matches:
            assert len(match["provider_health_digests"]) == 1
            health = ProviderHealthRepository(store).get(match["provider_health_digests"][0])
            assert health is not None and health.provider.provider_id == "open-meteo"
            assert health.provenance
            assert match["response_artifact_digest"] is not None
        calls = len(client.calls)
        assert (
            repo.build(
                freeze.freeze_id,
                policy,
                weather_client=client,
                context_fixtures=reversed(context),
                locations=locations,
            )
            == result
        )
        assert len(client.calls) == calls
        assert (
            repo.replay(result.digest, freeze_id=freeze.freeze_id, policy_digest=policy) == result
        )
        # F11 never publishes into the T05-bound legacy evidence tables.
        connection = store._connection_for_repository()
        assert connection.execute("SELECT COUNT(*) FROM workload_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM weather_evidence").fetchone()[0] == 0


def test_exact_freeze_policy_and_membership_are_never_inferred(tmp_path: Path) -> None:
    import copy
    from dataclasses import replace

    import pytest

    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, F11Error
    from matchvet.fixture_coverage import assess_fixture_coverage
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError
    from matchvet.matchweek_membership import canonical_json
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        freezes = MatchweekMembershipRepository(store)
        first = freezes.get_by_id(freeze_id)
        assert first is not None
        original = FixtureCoverageRepository(store).get(first.assessment_digest)
        assert original is not None
        changed = assess_fixture_coverage(
            scopes=tuple(s.scope for s in original.scope_assessments),
            provider_attempts=original.provider_attempts,
            coverage_evidence=original.coverage_evidence,
            fixture_revisions=original.fixture_revisions,
            identity_resolutions=original.identity_resolutions,
            freshness_results=tuple(
                replace(f, evaluated_at_utc="2026-09-17T13:00:00.000000+00:00")
                for f in original.freshness_results
            ),
        )
        FixtureCoverageRepository(store).persist(changed)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(changed))
        second = freezes.freeze_exact(
            "2026-27", "2026-09-25", changed.digest, "matchvet:matchweek-membership", "1"
        )
        assert first.memberships[0].fixture_id == second.memberships[0].fixture_id
        assert first.freeze_id != second.freeze_id
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        wrong_policy = cutoffs.persist_policy(CutoffPolicy("test", "2", 7200))
        cutoffs.persist_for_freeze(second.freeze_id, policy)
        repo = F11EvidenceRepository(store)
        # A newer same-fixture freeze has cutoffs; it cannot substitute for first.
        with pytest.raises(MatchEvidenceCutoffError, match="cutoff"):
            repo.build(first.freeze_id, policy, weather_client=None)
        with pytest.raises(F11Error, match="freeze"):
            repo.build("2026-09-25", policy, weather_client=None)
        with pytest.raises(MatchEvidenceCutoffError):
            repo.build(second.freeze_id, wrong_policy, weather_client=None)
        cutoffs.persist_for_freeze(first.freeze_id, policy)
        evidence = repo.build(first.freeze_id, policy, weather_client=None)
        newer = repo.build(second.freeze_id, policy, weather_client=None)
        assert evidence.digest != newer.digest
        assert (
            evidence.to_dict()["matches"][0]["cutoff"]["membership_id"]
            != (newer.to_dict()["matches"][0]["cutoff"]["membership_id"])
        )
        with pytest.raises(F11Error):
            repo.replay(evidence.digest, freeze_id=second.freeze_id, policy_digest=policy)
        with pytest.raises((F11Error, MatchEvidenceCutoffError)):
            repo.replay(evidence.digest, freeze_id=first.freeze_id, policy_digest=wrong_policy)
        for field in (
            "freeze_id",
            "freeze_digest",
            "policy_digest",
            "membership_id",
            "membership_digest",
            "fixture_id",
            "fixture_revision_ref",
            "fixture_revision_digest",
            "cutoff_id",
            "digest",
        ):
            forged = copy.deepcopy(evidence.to_dict())
            forged["matches"][0]["cutoff"][field] = "wrong-reference"
            digest = (
                ArtifactStore(store)
                .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
                .digest
            )
            with pytest.raises(F11Error, match="cutoff"):
                repo.replay(digest, freeze_id=first.freeze_id, policy_digest=policy)
        for match_count in (0, 2):
            forged = evidence.to_dict()
            forged["matches"] *= match_count
            digest = (
                ArtifactStore(store)
                .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
                .digest
            )
            with pytest.raises(F11Error, match="coverage"):
                repo.replay(digest, freeze_id=first.freeze_id, policy_digest=policy)


def test_replay_refuses_changed_target_facts_and_other_acquisition_health(tmp_path: Path) -> None:
    import json
    from dataclasses import replace

    import pytest

    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, HISTORY_MEDIA_TYPE, F11Error
    from matchvet.matchweek_membership import canonical_json
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import (
        StaticWeatherClient,
        VenueLocation,
        WeatherEvidenceBuilder,
        WeatherRequest,
        WeatherTarget,
    )
    from matchvet.workload import WorkloadCalculator, load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
        history = load_canonical_fixture_history(store)
        target = history[0]
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        request = WeatherRequest(
            target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
        )
        payload = {
            "latitude": 6.5,
            "longitude": 3.4,
            "forecast_issue_time": "2026-09-25T10:00:00Z",
            "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
        }
        client = StaticWeatherClient(
            {request.url: payload}, retrieved_at_utc="2026-09-25T12:00:00Z"
        )
        repo = F11EvidenceRepository(store)
        evidence = repo.build(
            freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
        )
        artifacts = ArtifactStore(store)
        other = WeatherEvidenceBuilder(
            StaticWeatherClient(
                {
                    request.url: {
                        **payload,
                        "hourly": {"time": [request.interval_start_utc], "temperature_2m": [99]},
                    }
                },
                retrieved_at_utc="2026-09-25T12:00:00Z",
            ),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
                ),
            )
        )
        forged = evidence.to_dict()
        forged["matches"][0]["provider_health_digests"] = [other.provider_health_records[0].digest]
        digest = artifacts.publish_artifact(
            canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE
        ).digest
        with pytest.raises(F11Error, match="F09"):
            repo.replay(digest, freeze_id=freeze_id, policy_digest=policy)
        forged_history = (replace(target, home_team_id="forged-home"),)
        forged = evidence.to_dict()
        forged["history_artifact_digest"] = artifacts.publish_artifact(
            canonical_json([f.to_dict() for f in forged_history]).encode(), HISTORY_MEDIA_TYPE
        ).digest
        forged["matches"][0]["workload"] = json.loads(
            canonical_json(
                WorkloadCalculator(forged_history, cutoff_utc=cutoff.cutoff_at_utc)
                .calculate(forged_history[0])
                .to_dict()
            )
        )
        digest = artifacts.publish_artifact(
            canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE
        ).digest
        with pytest.raises(F11Error, match="revision"):
            repo.replay(digest, freeze_id=freeze_id, policy_digest=policy)


def test_replay_refuses_corrupt_artifacts_and_source_references(tmp_path: Path) -> None:
    import pytest

    from matchvet.artifacts import ArtifactError, ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, F11Error
    from matchvet.matchweek_membership import canonical_json
    from matchvet.weather import VenueLocation

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoffs.persist_for_freeze(freeze_id, policy)
        repo = F11EvidenceRepository(store)
        evidence = repo.build(freeze_id, policy, weather_client=None)
        forged = evidence.to_dict()
        forged["history_artifact_digest"] = "0" * 64
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F11Error, match="artifact"):
            repo.replay(digest, freeze_id=freeze_id, policy_digest=policy)
        location = VenueLocation(
            "stadium",
            "Stadium",
            6.5,
            3.4,
            "venue",
            "https://venue.test",
            "2026-09-01T10:00:00Z",
            "missing-source-capture",
        )
        with pytest.raises(F11Error, match="capture"):
            repo.build(
                freeze_id,
                policy,
                weather_client=None,
                locations={evidence.to_dict()["matches"][0]["cutoff"]["fixture_id"]: location},
            )
        metadata = store.artifact_metadata(evidence.to_dict()["history_artifact_digest"])
        assert metadata is not None
        (tmp_path / metadata.relative_path).write_bytes(b"corrupt")
        with pytest.raises(ArtifactError):
            repo.replay(evidence.digest, freeze_id=freeze_id, policy_digest=policy)


def test_weather_location_issue_and_retrieval_each_obey_the_match_cutoff(tmp_path: Path) -> None:
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
        target = load_canonical_fixture_history(store)[0]
        repo = F11EvidenceRepository(store)
        for label, observed, issue, retrieved, reason in (
            (
                "location",
                "2026-09-25T19:00:00Z",
                "2026-09-25T10:00:00Z",
                "2026-09-25T12:00:00Z",
                "LOCATION_POST_CUTOFF",
            ),
            (
                "issue",
                "2026-09-01T10:00:00Z",
                "2026-09-25T19:00:00Z",
                "2026-09-25T12:00:00Z",
                "FORECAST_POST_CUTOFF",
            ),
            (
                "retrieval",
                "2026-09-01T10:00:00Z",
                "2026-09-25T10:00:00Z",
                "2026-09-25T19:00:00Z",
                "FORECAST_POST_CUTOFF",
            ),
        ):
            location = VenueLocation(
                label, label, 6.5, 3.4, "venue", "https://venue.test", observed
            )
            request = WeatherRequest(
                target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
            )
            client = StaticWeatherClient(
                {
                    request.url: {
                        "latitude": 6.5,
                        "longitude": 3.4,
                        "forecast_issue_time": issue,
                        "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
                    }
                },
                retrieved_at_utc=retrieved,
            )
            result = repo.build(
                freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
            )
            match = result.to_dict()["matches"][0]
            assert match["weather"]["state"] == "UNKNOWN"
            assert match["weather"]["unknown_reason"] == reason
            assert len(match["provider_health_digests"]) == (0 if label == "location" else 1)
            assert repo.replay(result.digest, freeze_id=freeze_id, policy_digest=policy) == result


def test_unavailable_weather_retains_exact_failure_health(tmp_path: Path) -> None:
    import pytest

    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, F11Error
    from matchvet.matchweek_membership import canonical_json
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import (
        VenueLocation,
        WeatherEvidenceBuilder,
        WeatherHTTPResponse,
        WeatherPolicyError,
        WeatherRequest,
        WeatherTarget,
        WeatherUnavailable,
    )
    from matchvet.workload import load_canonical_fixture_history

    class FailingClient:
        def __init__(self, denied: bool) -> None:
            self.denied = denied

        def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
            if self.denied:
                raise WeatherPolicyError("Denied")
            raise WeatherUnavailable("Network unavailable")

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
        target = load_canonical_fixture_history(store)[0]
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        repo = F11EvidenceRepository(store)
        result = repo.build(
            freeze_id,
            policy,
            weather_client=FailingClient(False),
            locations={target.fixture_id: location},
        )
        assert result.to_dict()["matches"][0]["weather"]["state"] == "UNKNOWN"
        assert repo.replay(result.digest, freeze_id=freeze_id, policy_digest=policy) == result
        denied = WeatherEvidenceBuilder(
            FailingClient(True), provider_health_repository=ProviderHealthRepository(store)
        ).build(
            (
                WeatherTarget(
                    target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
                ),
            )
        )
        forged = result.to_dict()
        forged["matches"][0]["provider_health_digests"] = [denied.provider_health_records[0].digest]
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F11Error, match="F09"):
            repo.replay(digest, freeze_id=freeze_id, policy_digest=policy)


def test_replay_preserves_named_artifact_after_reopening_store(tmp_path: Path) -> None:
    database = tmp_path / "matchvet.sqlite3"
    with open_store(database, private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoffs.persist_for_freeze(freeze_id, policy)
        evidence = F11EvidenceRepository(store).build(freeze_id, policy, weather_client=None)
    with open_store(database, private_root=tmp_path) as store:
        replayed = F11EvidenceRepository(store).replay(
            evidence.digest, freeze_id=freeze_id, policy_digest=policy
        )
        assert replayed.to_bytes() == evidence.to_bytes()
        assert replayed.digest == evidence.digest


def test_existing_v1_weather_response_artifact_keeps_its_metadata(tmp_path: Path) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
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
        raw = client.fetch(request).content
        artifacts = ArtifactStore(store)
        # Exactly the publication contract used by the unchanged V1 weather recorder.
        legacy = artifacts.publish_artifact(raw, "application/json", retention_class="REUSABLE")
        metadata = store.artifact_metadata(legacy.digest)
        repo = F11EvidenceRepository(store)
        evidence = repo.build(
            freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
        )
        assert store.artifact_metadata(legacy.digest) == metadata
        assert artifacts.read_artifact(legacy.digest) == raw
        assert repo.replay(evidence.digest, freeze_id=freeze_id, policy_digest=policy) == evidence


def test_f11_weather_attempt_is_typed_and_retry_does_not_fetch_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.artifacts import ArtifactRecord, ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE, F11Error
    from matchvet.f12 import ContextualAttemptRepository
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
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
        repo = F11EvidenceRepository(store)
        publish = repo.artifacts.publish_artifact

        def interrupt_evidence_publication(
            content: bytes,
            media_type: str,
            *,
            expected_digest: str | None = None,
            retention_class: str = "PROTECTED",
        ) -> ArtifactRecord:
            if media_type == EVIDENCE_MEDIA_TYPE:
                raise RuntimeError("simulated interruption before evidence publication")
            return publish(
                content,
                media_type,
                expected_digest=expected_digest,
                retention_class=retention_class,
            )

        monkeypatch.setattr(repo.artifacts, "publish_artifact", interrupt_evidence_publication)
        with pytest.raises(RuntimeError, match="simulated interruption"):
            repo.build(
                freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
            )
        monkeypatch.setattr(repo.artifacts, "publish_artifact", publish)
        evidence = repo.build(
            freeze_id, policy, weather_client=None, locations={target.fixture_id: location}
        )
        match = evidence.to_dict()["matches"][0]
        attempt_ref = match["contextual_attempt"]
        assert attempt_ref["attempt_id"].startswith("f12:")
        value = ContextualAttemptRepository(store).get(attempt_ref["attempt_id"])
        health_digest = match["provider_health_digests"][0]
        health = ProviderHealthRepository(store).get(health_digest)
        assert health is not None
        assert value.outcome.value == "SUCCEEDED"
        assert value.fixture_id == cutoff.fixture_id
        assert (value.cutoff_id, value.cutoff_digest) == (cutoff.cutoff_id, cutoff.digest)
        assert value.requested_scope_id == health.requested_scope.scope_id
        assert value.provider_health_digest == health_digest
        assert value.response_artifact_digest == match["response_artifact_digest"]
        assert (
            value.to_bytes() == ContextualAttemptRepository(store).get(value.attempt_id).to_bytes()
        )
        assert len(client.calls) == 1

        from matchvet.artifacts import ArtifactStore
        from matchvet.f11 import EVIDENCE_MEDIA_TYPE
        from matchvet.matchweek_membership import canonical_json

        forged = evidence.to_dict()
        forged["matches"][0]["contextual_attempt"]["digest"] = "sha256:" + "0" * 64
        bad_digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), EVIDENCE_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F11Error, match="F12 attempt digest"):
            repo.replay(bad_digest, freeze_id=freeze_id, policy_digest=policy)


@pytest.mark.parametrize("malformed", [False, True])
def test_f11_keeps_unavailable_and_malformed_requests_as_failed_attempts(
    tmp_path: Path, malformed: bool
) -> None:
    from matchvet.f12 import AttemptOutcome, AttemptUsability, ContextualAttemptRepository
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy)[0]
        target = load_canonical_fixture_history(store)[0]
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        request = WeatherRequest(
            target.fixture_id, target.kickoff_utc or "", cutoff.cutoff_at_utc, location
        )
        response = b"not-json" if malformed else None
        client = StaticWeatherClient(
            {request.url: response} if response is not None else {},
            retrieved_at_utc="2026-09-25T12:00:00Z",
        )
        evidence = F11EvidenceRepository(store).build(
            freeze_id, policy, weather_client=client, locations={target.fixture_id: location}
        )
        match = evidence.to_dict()["matches"][0]
        reference = match["contextual_attempt"]
        attempt = ContextualAttemptRepository(store).get(reference["attempt_id"])
        assert attempt.outcome is AttemptOutcome.FAILED
        assert attempt.usability is AttemptUsability.UNUSABLE
        assert attempt.provider_health_digest == match["provider_health_digests"][0]
        assert (attempt.response_artifact_digest is not None) is malformed
        assert attempt.error_type is not None

        assert len(client.calls) == 1

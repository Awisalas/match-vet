from pathlib import Path

from test_match_evidence_cutoff import _freeze

from matchvet.f11 import F11EvidenceRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.store import open_store


def test_exact_contract_replays_and_keeps_unavailable_models(tmp_path: Path) -> None:
    from matchvet.f13 import ModelContractRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, policy, weather_client=None)
        repo = ModelContractRepository(store)
        assert repo.retain_history(()) == ()
        result = repo.build(evidence.digest, cutoff.cutoff_id, history=())
        assert repo.build(evidence.digest, cutoff.cutoff_id, history=()) == result
        assert repo.replay(result.digest, evidence.digest, cutoff.cutoff_id) == result
        value = result.to_dict()
        assert value["inputs"]["membership_digest"] == cutoff.membership_digest
        assert value["inputs"]["cutoff_digest"] == cutoff.digest
        assert value["inputs"]["evidence_set_digest"] == evidence.digest
        assert set(value["results"]) == {
            "FULL_TIME_GOALS",
            "FIRST_HALF_GOALS",
            "SECOND_HALF_GOALS",
            "CORNERS",
        }
        for family in value["results"].values():
            assert family["model_availability"] == "MODEL_UNAVAILABLE"
            assert family["uncertainty_engine"]["model_version"] == "t14-calibration-uncertainty-v1"
            assert family["input_lineage"]["engine_contract"] == value["inputs"]["engine_contract"]
            assert not family["estimated_distribution"]
            assert family["calibrated"]["status"] == "MODEL_UNAVAILABLE"
        assert value["inputs"]["context"]["weather"]["state"] == "UNKNOWN"


def test_models_use_only_cutoff_valid_history_and_keep_exact_lineage(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_t11 import _history

    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import INPUT_MEDIA_TYPE, ModelContractRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, policy, weather_client=None)
        repo = ModelContractRepository(store)
        target = repo.build(evidence.digest, cutoff.cutoff_id, history=()).to_dict()["inputs"][
            "target"
        ]
        rows = tuple(
            replace(
                m,
                home_team_id=target["home_team_id"]
                if m.home_team_id == "team-home"
                else target["away_team_id"]
                if m.home_team_id == "team-away"
                else m.home_team_id,
                away_team_id=target["home_team_id"]
                if m.away_team_id == "team-home"
                else target["away_team_id"]
                if m.away_team_id == "team-away"
                else m.away_team_id,
                half_time_home_goals=0,
                half_time_away_goals=0,
                corners_home=4 + i % 4,
                corners_away=3 + i % 3,
                observed_at_utc="2026-09-11T00:00:00Z",
            )
            for i, m in enumerate(_history())
        )
        rows = repo.retain_history(rows)
        future = replace(rows[0], fixture_id="future", observed_at_utc="2026-09-26T00:00:00Z")
        unknown = replace(rows[0], fixture_id="unknown", observed_at_utc=None)
        result = repo.build(evidence.digest, cutoff.cutoff_id, history=(*rows, future, unknown))
        value = result.to_dict()
        snapshot_digest = value["inputs"]["history_snapshot_digest"]
        metadata = store.artifact_metadata(snapshot_digest)
        assert metadata is not None and metadata.media_type == INPUT_MEDIA_TYPE
        import json

        snapshot = json.loads(ArtifactStore(store).read_artifact(snapshot_digest))
        assert {m["fixture_id"] for m in snapshot["history"]} == {m.fixture_id for m in rows}
        assert {m["fixture_id"] for m in value["inputs"]["excluded_history"]} == {
            "future",
            "unknown",
        }
        for model in value["results"].values():
            assert model["model_availability"] == "AVAILABLE"
            assert model["estimated_distribution"]
            assert model["calibrated"]["status"] == "MODEL_UNAVAILABLE"
            assert not model["calibrated"]["estimated_probabilities"]
            assert model["feature_input_ids"] == model["fit"]["feature_input_ids"]
            assert model["feature_input_digests"] == model["fit"]["feature_input_digests"]
            assert model["training_input_ids"] == model["fit"]["training_input_ids"]
            assert model["training_input_digests"] == model["fit"]["training_input_digests"]
            assert model["training_input_ids"] == sorted(
                {value for row in rows for value in (row.fixture_id, *row.source_assertion_ids)}
            )
            import hashlib

            from matchvet.matchweek_membership import canonical_json

            assert rows[0].source_digest is not None
            expected_digests = {rows[0].source_digest}
            if model["model_family"] == "CORNERS":
                expected_digests.update(
                    hashlib.sha256(canonical_json(row).encode()).hexdigest()
                    for row in snapshot["history"]
                )
            assert model["training_input_digests"] == sorted(expected_digests)
        assert (
            repo.build(
                evidence.digest, cutoff.cutoff_id, history=(*reversed(rows), unknown, future)
            )
            == result
        )
        assert repo.replay(result.digest, evidence.digest, cutoff.cutoff_id) == result
        unknown_rows = repo.retain_history(
            tuple(replace(m, metric_states={key: "UNKNOWN" for key in m.metrics}) for m in rows)
        )
        unavailable = repo.build(evidence.digest, cutoff.cutoff_id, history=unknown_rows).to_dict()
        for model in unavailable["results"].values():
            assert model["model_availability"] == "MODEL_UNAVAILABLE"
            assert not model["estimated_distribution"]
        assert any(f["state"] == "UNKNOWN" for f in unavailable["features"])


def test_contract_refuses_changed_cutoff_evidence_and_forged_lineage(tmp_path: Path) -> None:
    import pytest

    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import RESULT_MEDIA_TYPE, F13Error, ModelContractRepository
    from matchvet.matchweek_membership import canonical_json
    from matchvet.workload import WorkloadRules

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        repo = ModelContractRepository(store)
        f11 = F11EvidenceRepository(store)
        evidence = f11.build(freeze, policy, weather_client=None)
        result = repo.build(evidence.digest, cutoff.cutoff_id, history=())
        other_policy = cutoffs.persist_policy(CutoffPolicy("test", "2", 7200))
        other_cutoff = cutoffs.persist_for_freeze(freeze, other_policy)[0]
        other_evidence = f11.build(freeze, other_policy, weather_client=None)
        other_result = repo.build(other_evidence.digest, other_cutoff.cutoff_id, history=())
        assert other_result.to_dict()["input_digest"] != result.to_dict()["input_digest"]
        with pytest.raises((F13Error, ValueError)):
            repo.replay(result.digest, evidence.digest, other_cutoff.cutoff_id)
        changed = f11.build(
            freeze, policy, weather_client=None, rules=WorkloadRules(name="test-change")
        )
        assert changed.digest != evidence.digest
        assert (
            repo.build(changed.digest, cutoff.cutoff_id, history=()).to_dict()["input_digest"]
            != result.to_dict()["input_digest"]
        )
        with pytest.raises(F13Error):
            repo.replay(result.digest, changed.digest, cutoff.cutoff_id)
        for key, replacement in [
            ("schema_version", 99),
            ("schema_version", 2.0),
            ("input_digest", "0" * 64),
        ]:
            forged = result.to_dict()
            forged[key] = replacement
            digest = (
                ArtifactStore(store)
                .publish_artifact(canonical_json(forged).encode(), RESULT_MEDIA_TYPE)
                .digest
            )
            with pytest.raises(F13Error):
                repo.replay(digest, evidence.digest, cutoff.cutoff_id)
        forged = result.to_dict()
        forged["inputs"]["odds"] = 1.5
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), RESULT_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F13Error, match="input schema"):
            repo.replay(digest, evidence.digest, cutoff.cutoff_id)
        forged = result.to_dict()
        forged["inputs"]["excluded_history"] = [42]
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), RESULT_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F13Error, match="excluded"):
            repo.replay(digest, evidence.digest, cutoff.cutoff_id)
        from matchvet.f13 import INPUT_MEDIA_TYPE

        forged = result.to_dict()
        forged["inputs"]["history_snapshot_digest"] = (
            ArtifactStore(store)
            .publish_artifact(
                canonical_json({"schema_version": 2, "history": {}}).encode(),
                INPUT_MEDIA_TYPE,
            )
            .digest
        )
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), RESULT_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F13Error, match="collection"):
            repo.replay(digest, evidence.digest, cutoff.cutoff_id)
        forged = result.to_dict()
        forged["results"]["CORNERS"]["model_fit_digest"] = "0" * 64
        digest = (
            ArtifactStore(store)
            .publish_artifact(canonical_json(forged).encode(), RESULT_MEDIA_TYPE)
            .digest
        )
        with pytest.raises(F13Error):
            repo.replay(digest, evidence.digest, cutoff.cutoff_id)


def test_calibration_cases_require_exact_prior_prediction_lineage(tmp_path: Path) -> None:
    import pytest

    from matchvet.f13 import CalibrationCase, F13Error, ModelContractRepository
    from matchvet.t14 import ModelFamily

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, policy, weather_client=None)
        repo = ModelContractRepository(store)
        case = CalibrationCase(
            prediction_contract_digest="0" * 64,
            fixture_id="wrong-fixture",
            family=ModelFamily.FULL_TIME_GOALS,
        )
        with pytest.raises(F13Error):
            repo.build(evidence.digest, cutoff.cutoff_id, history=(), calibration_cases=(case,))


def test_model_artifacts_are_protected_and_bound_to_input_identity(tmp_path: Path) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import ModelContractRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, policy, weather_client=None)
        result = ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=())
        for model in result.to_dict()["results"].values():
            for field in (
                "model_artifact_digest",
                "prediction_artifact_digest",
                "calibration_artifact_digest",
            ):
                metadata = store.artifact_metadata(model[field])
                assert metadata is not None and metadata.retention_class == "PROTECTED"
                import json

                artifact = json.loads(ArtifactStore(store).read_artifact(model[field]))
                assert artifact["input_digest"] == model["input_digest"]
                assert artifact["model_family"] == model["model_family"]


def test_all_families_retain_available_calibration_and_uncertainty(tmp_path: Path) -> None:
    from dataclasses import replace
    from datetime import datetime, timedelta

    from test_matchweek_membership import _persistable_schedule_assessment
    from test_t11 import _history

    from matchvet.f13 import CalibrationCase, ModelContractRepository
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.t14 import ModelFamily
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            tuple(
                (f"2026-09-{day}", "20:00", "Home United", f"Away City {day}")
                for day in range(25, 29)
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        boundaries = sorted(
            cutoffs.persist_for_freeze(freeze.freeze_id, policy), key=lambda c: c.cutoff_at_utc
        )
        evidence = F11EvidenceRepository(store).build(freeze.freeze_id, policy, weather_client=None)
        targets = {f.fixture_id: f for f in load_canonical_fixture_history(store)}
        target = targets[boundaries[0].fixture_id]
        aliases = {"team-home": target.home_team_id, "team-away": target.away_team_id}
        history = tuple(
            replace(
                m,
                home_team_id=aliases.get(m.home_team_id, m.home_team_id),
                away_team_id=aliases.get(m.away_team_id, m.away_team_id),
                half_time_home_goals=0,
                half_time_away_goals=0,
                corners_home=4 + i % 4,
                corners_away=3 + i % 3,
                observed_at_utc="2026-09-11T00:00:00Z",
            )
            for i, m in enumerate(_history())
        )
        repo = ModelContractRepository(store)
        cases: list[CalibrationCase] = []
        outcomes = []
        for i, cutoff in enumerate(boundaries[:3]):
            fixture = targets[cutoff.fixture_id]
            prior_history = tuple(
                replace(m, away_team_id=fixture.away_team_id)
                if m.away_team_id == target.away_team_id
                else replace(m, home_team_id=fixture.away_team_id)
                if m.home_team_id == target.away_team_id
                else m
                for m in history
            )
            prediction = repo.build(
                evidence.digest, cutoff.cutoff_id, history=repo.retain_history(prior_history)
            )
            fixture = targets[cutoff.fixture_id]
            assert fixture.kickoff_utc is not None
            outcome_time = (
                datetime.fromisoformat(fixture.kickoff_utc) + timedelta(hours=2)
            ).isoformat()
            outcomes.append(
                replace(
                    history[0],
                    fixture_id=fixture.fixture_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    kickoff_utc=fixture.kickoff_utc,
                    observed_at_utc=outcome_time,
                    full_time_home_goals=1 + i,
                    full_time_away_goals=i,
                    half_time_home_goals=i,
                    half_time_away_goals=0,
                    corners_home=5 + i,
                    corners_away=4 + i,
                    source_digest=f"{i + 99:064x}",
                    source_assertion_ids=(f"outcome-{i}",),
                )
            )
            cases.extend(
                CalibrationCase(prediction.digest, fixture.fixture_id, family)
                for family in ModelFamily
            )
        cutoff = boundaries[3]
        last = targets[cutoff.fixture_id]
        history = tuple(
            replace(m, away_team_id=last.away_team_id)
            if m.away_team_id == target.away_team_id
            else replace(m, home_team_id=last.away_team_id)
            if m.home_team_id == target.away_team_id
            else m
            for m in history
        )
        result = repo.build(
            evidence.digest,
            cutoff.cutoff_id,
            history=repo.retain_history((*history, *outcomes)),
            calibration_cases=cases,
        )
        for model in result.to_dict()["results"].values():
            assert model["calibration"]["status"] == "AVAILABLE"
            assert model["calibrated"]["status"] == "AVAILABLE"
            assert model["calibrated"]["probability_intervals"]
            assert model["calibrated"]["calibration_digest"] == model["calibration_digest"]
            assert model["calibration"]["used_fixture_ids"] == sorted(
                m.fixture_id for m in outcomes
            )
            assert model["calibration"]["training_input_digests"]
        assert repo.replay(result.digest, evidence.digest, cutoff.cutoff_id) == result
        import pytest

        from matchvet.f13 import F13Error

        reversed_outcome = replace(
            outcomes[0],
            home_team_id=outcomes[0].away_team_id,
            away_team_id=outcomes[0].home_team_id,
        )
        with pytest.raises(F13Error, match="fixture identity"):
            repo.build(
                evidence.digest,
                cutoff.cutoff_id,
                history=repo.retain_history((*history, reversed_outcome, *outcomes[1:])),
                calibration_cases=cases,
            )


def test_declared_history_without_retained_source_is_refused(tmp_path: Path) -> None:
    from dataclasses import replace

    import pytest
    from test_t11 import _history

    from matchvet.f13 import F13Error, ModelContractRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, policy, weather_client=None)
        history = (replace(_history()[0], observed_at_utc="2026-09-11T00:00:00Z"),)
        with pytest.raises(F13Error, match="source"):
            ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=history)
        repo = ModelContractRepository(store)
        retained = repo.retain_history(history)
        forged = (replace(retained[0], full_time_home_goals=9),)
        with pytest.raises(F13Error, match="source row"):
            repo.build(evidence.digest, cutoff.cutoff_id, history=forged)


def test_observed_context_retains_attempt_but_cannot_supply_quantitative_history(
    tmp_path: Path,
) -> None:
    from matchvet.f13 import ModelContractRepository
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest
    from matchvet.workload import load_canonical_fixture_history

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        target = load_canonical_fixture_history(store)[0]
        assert target.kickoff_utc is not None
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", "2026-09-01T10:00:00Z"
        )
        request = WeatherRequest(
            target.fixture_id, target.kickoff_utc, cutoff.cutoff_at_utc, location
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
            freeze, policy, weather_client=client, locations={target.fixture_id: location}
        )
        value = (
            ModelContractRepository(store)
            .build(evidence.digest, cutoff.cutoff_id, history=())
            .to_dict()
        )
        weather = next(a for a in value["research_attempts"] if a["requirement_id"] == "M-WEATHER")
        assert weather["performed"] is True
        assert weather["outcome"] == "OBSERVED"
        assert (
            value["inputs"]["context"]["contextual_attempt"]["attempt_id"]
            in weather["source_assertion_ids"]
        )
        assert next(f for f in value["features"] if f["name"] == "M-WEATHER")["state"] == "OBSERVED"
        for model in value["results"].values():
            assert model["model_availability"] == "MODEL_UNAVAILABLE"
            assert not model["estimated_distribution"]


def test_engine_version_identity_is_deterministic_without_per_match_inputs() -> None:
    from matchvet.f13 import engine_version_identity

    identity = engine_version_identity()

    assert len(identity) == 64
    assert set(identity) <= set("0123456789abcdef")
    assert engine_version_identity() == identity

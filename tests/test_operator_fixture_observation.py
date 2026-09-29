from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from matchvet.artifacts import ArtifactStore
from matchvet.cli import _parser, main
from matchvet.fixture_coverage import (
    MatchweekScheduleState,
    ScopeCoverageState,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.ingestion import (
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    IngestionPlan,
    StaticSourceFetcher,
    canonical_key,
    deterministic_identifier,
    league_by_key,
)
from matchvet.operator_fixture_observation import (
    OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION,
    OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE,
    OPERATOR_FIXTURE_OBSERVATION_POLICY_ID,
    OfficialFixtureObservationInput,
    OperatorFixtureObservationRepository,
    OperatorOfficialFixtureObservation,
    operator_fixture_observation_from_canonical_json,
    operator_fixture_observation_policy_v1,
    operator_fixture_observation_to_canonical_json,
)
from matchvet.runs import GIB, ResourceObservation
from matchvet.store import CanonicalIdentifier, Store, open_store
from matchvet.t17 import backup_store, restore_backup, verify_backup


def _seed_belgian_teams(store: object, names: tuple[str, ...]) -> None:
    league = league_by_key("belgian_pro_league")
    league_id = deterministic_identifier("league", league.key)
    created_at = "2026-09-01T00:00:00+00:00"
    with store.transaction() as tx:  # type: ignore[attr-defined]
        tx.add_identifier_if_missing(CanonicalIdentifier("league", league_id))
        tx.execute(
            """
            INSERT INTO target_leagues (
                league_id, league_key, canonical_name, country, football_data_code,
                openfootball_code, source_timezone, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(league_id) DO NOTHING
            """,
            (
                league_id,
                league.key,
                league.name,
                league.country,
                league.football_data_code,
                league.openfootball_code,
                league.timezone,
                created_at,
            ),
        )
        for name in names:
            team_id = deterministic_identifier("team", f"{league.key}:{canonical_key(name)}")
            tx.add_identifier_if_missing(CanonicalIdentifier("team", team_id))
            tx.execute(
                """
                INSERT INTO teams (
                    team_id, league_id, canonical_name, normalized_name, created_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO NOTHING
                """,
                (team_id, league_id, name, canonical_key(name), created_at),
            )


def _valid_input(**changes: str) -> OfficialFixtureObservationInput:
    values: dict[str, str | None] = {
        "league_key": "belgian_pro_league",
        "season": "2026-27",
        "friday": "2026-10-09",
        "home": "Synthetic North FC",
        "away": "Synthetic South FC",
        "kickoff": "2026-10-09T20:00:00+02:00",
        "status": "SCHEDULED",
        "official_url": "https://www.proleague.be/jpl-kalender!",
        "publication_id": "jpl-kalender",
        "publication_type": "OFFICIAL_COMPETITION_CALENDAR",
        "title": "Synthetic test citation",
        "publication_date": "2026-09-29",
        "operator_id": "operator-test",
    }
    values.update(changes)
    return OfficialFixtureObservationInput(**values)  # type: ignore[arg-type]


def _open_observation_store(tmp_path: Path) -> tuple[Path, Store]:
    private_root = tmp_path / "lf05-isolated-store"
    private_root.mkdir()
    return private_root, open_store(private_root / "matchvet.sqlite3", private_root=private_root)


def _instant_observation() -> OperatorOfficialFixtureObservation:
    policy = operator_fixture_observation_policy_v1()
    return OperatorOfficialFixtureObservation(
        contract_version=OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION,
        schema_version=1,
        league_key="belgian_pro_league",
        season="2026-27",
        matchweek_friday="2026-10-09",
        scope_id="belgian_pro_league:2026-27:2026-10-09",
        home_source_name="Synthetic North FC",
        away_source_name="Synthetic South FC",
        home_team_id="team-synthetic-north",
        away_team_id="team-synthetic-south",
        kickoff_precision="INSTANT",
        kickoff_utc="2026-10-09T18:00:00+00:00",
        source_local_date="2026-10-09",
        fixture_status="SCHEDULED",
        publisher_id=policy.publisher_id,
        publisher_name=policy.publisher_name,
        competition_id=policy.competition_id,
        competition_name=policy.competition_name,
        publication_id="jpl-kalender",
        publication_type="OFFICIAL_COMPETITION_CALENDAR",
        official_url="https://www.proleague.be/jpl-kalender!",
        title_or_publication_id="Synthetic test citation",
        publication_date="2026-09-29",
        operator_id="operator-test",
        observed_at_utc="2026-09-29T12:00:00+00:00",
        policy_id=OPERATOR_FIXTURE_OBSERVATION_POLICY_ID,
        policy_version="1",
        policy_digest=policy.digest,
        mode="RESEARCH_ONLY",
        access_method="MANUAL_CITATION",
        source_class="OFFICIAL_COMPETITION",
    )


def test_observation_contract_has_deterministic_canonical_codec() -> None:
    observation = _instant_observation()

    first = operator_fixture_observation_to_canonical_json(observation)
    second = operator_fixture_observation_to_canonical_json(observation)
    replayed = operator_fixture_observation_from_canonical_json(first)

    assert first == second
    assert replayed == observation
    assert observation.digest.startswith("sha256:")
    assert OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE == (
        "application/vnd.matchvet.operator-official-fixture-observation+json"
    )


def test_observation_contract_rejects_noncanonical_or_corrupt_bytes() -> None:
    canonical = operator_fixture_observation_to_canonical_json(_instant_observation())

    try:
        operator_fixture_observation_from_canonical_json(canonical + " ")
    except ValueError as error:
        assert "canonical" in str(error).casefold()
    else:
        raise AssertionError("noncanonical observation bytes must be rejected")

    try:
        operator_fixture_observation_from_canonical_json(
            canonical.replace("Synthetic North FC", "Synthetic X FC")
        )
    except ValueError as error:
        assert "digest" in str(error).casefold()
    else:
        raise AssertionError("altered observation facts must be rejected")


def test_record_persists_only_canonical_citation_and_ordinary_fixture_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import matchvet.ingestion as ingestion

    def refuse_official_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("LF05 must not fetch official URLs.")

    monkeypatch.setattr(ingestion, "urlopen", refuse_official_fetch)
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)

        recorded = repository.record(_valid_input())

        assert store.status.schema_version == 13
        assert recorded.observation.scope_id == "belgian_pro_league:2026-27:2026-10-09"
        assert recorded.observation.kickoff_utc == "2026-10-09T18:00:00+00:00"
        assert recorded.observation.mode == "RESEARCH_ONLY"
        assert recorded.import_result.fixtures_imported == 1
        assert recorded.import_result.unresolved_rows == 0
        artifact = ArtifactStore(store).verify_artifact(recorded.artifact_digest)
        assert artifact.media_type == OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE
        content = ArtifactStore(store).read_artifact(recorded.artifact_digest)
        assert b"<html" not in content.lower()
        assert b"calendar page body" not in content
        assert json.loads(content)["observation"]["official_url"] == _valid_input().official_url

        importer = FixtureHistoryImporter(store, private_root=private_root)
        fixture = next(
            item for item in importer.fixtures() if item.fixture_id == recorded.fixture_id
        )
        assert fixture.home_team_name == "Synthetic North FC"
        assert fixture.away_team_name == "Synthetic South FC"
        revision = importer.revisions(recorded.fixture_id)[0]
        assert revision.revision_id == recorded.revision_id
        assert revision.fixture_status == "SCHEDULED"
        assert revision.kickoff_precision == "INSTANT"
        assertions = tuple(
            item for item in importer.source_assertions() if item.capture_id == recorded.capture_id
        )
        assert {item.predicate for item in assertions} == {
            "home_team",
            "away_team",
            "kickoff",
            "fixture_status",
        }
        assert all(item.subject_key == recorded.fixture_id for item in assertions)
        assert len(importer.fixtures()) == 1
        assert len(importer.source_captures()) == 1
        assert FixtureCoverageRepository(store).list_for_matchweek("2026-27", "2026-10-09") == ()


def test_replaying_one_observation_keeps_one_capture_revision_and_assertion_set(
    tmp_path: Path,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)
        recorded = repository.record(_valid_input())

        replayed = repository.persist(recorded.observation)

        importer = FixtureHistoryImporter(store, private_root=private_root)
        assert replayed.capture_id == recorded.capture_id
        assert replayed.revision_id == recorded.revision_id
        assert replayed.import_result.from_existing_capture
        assert len(importer.source_captures()) == 1
        assert len(importer.source_assertions()) == 4
        assert len(importer.revisions(recorded.fixture_id)) == 1
        assert repository.get(recorded.artifact_digest).observation == recorded.observation


def test_observation_replay_fails_closed_when_artifact_bytes_are_corrupted(
    tmp_path: Path,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)
        recorded = repository.record(_valid_input())
        artifact = ArtifactStore(store).verify_artifact(recorded.artifact_digest)
        artifact_path = private_root / artifact.relative_path
        artifact_path.write_bytes(artifact_path.read_bytes() + b"corrupt")

        with pytest.raises(ValueError, match="corrupt"):
            repository.get(recorded.artifact_digest)


def test_new_citation_reuses_factual_revision_and_changed_status_appends_conflict(
    tmp_path: Path,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)
        first = repository.record(_valid_input())
        same_facts_new_citation = repository.record(
            _valid_input(title="Updated synthetic citation")
        )

        assert same_facts_new_citation.artifact_digest != first.artifact_digest
        assert same_facts_new_citation.capture_id != first.capture_id
        assert same_facts_new_citation.revision_id == first.revision_id
        importer = FixtureHistoryImporter(store, private_root=private_root)
        assert len(importer.revisions(first.fixture_id)) == 1
        assert len(importer.source_assertions()) == 8
        assert {item.capture_id for item in importer.source_assertions()} == {
            first.capture_id,
            same_facts_new_citation.capture_id,
        }

        changed_status = repository.record(_valid_input(status="CANCELLED"))

        assert changed_status.fixture_id == first.fixture_id
        assert changed_status.revision_id != first.revision_id
        assert {item.fixture_status for item in importer.revisions(first.fixture_id)} == {
            "SCHEDULED",
            "CANCELLED",
        }
        assert any(
            item.predicate == "fixture_status" and len(item.assertion_ids) == 3
            for item in importer.conflicts(first.fixture_id)
        )

        postponed = repository.record(_valid_input(status="POSTPONED"))
        assert postponed.fixture_id == first.fixture_id
        assert {item.fixture_status for item in importer.revisions(first.fixture_id)} == {
            "SCHEDULED",
            "CANCELLED",
            "POSTPONED",
        }

        changed_kickoff = repository.record(_valid_input(kickoff="2026-10-09T21:00:00+02:00"))
        assert changed_kickoff.fixture_id == first.fixture_id
        assert changed_kickoff.revision_id != first.revision_id
        assert changed_kickoff.revision_id != changed_status.revision_id
        assert any(item.predicate == "kickoff" for item in importer.conflicts(first.fixture_id))


def test_date_kickoff_stays_date_and_never_gets_a_fake_utc_value(tmp_path: Path) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)

        recorded = repository.record(_valid_input(kickoff="2026-10-10"))

        assert recorded.observation.kickoff_precision == "DATE"
        assert recorded.observation.kickoff_utc is None
        assert recorded.observation.source_local_date == "2026-10-10"
        revision = FixtureHistoryImporter(store, private_root=private_root).revisions(
            recorded.fixture_id
        )[0]
        assert revision.kickoff_utc is None
        assert revision.kickoff_local_text == "2026-10-10"
        assert revision.kickoff_precision == "DATE"


def test_policy_supports_exact_matchweeks_throughout_the_supported_season(
    tmp_path: Path,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)

        recorded = repository.record(
            _valid_input(
                friday="2026-10-16",
                kickoff="2026-10-16T20:00:00+02:00",
                title="Synthetic second matchweek citation",
            )
        )

        assert recorded.observation.scope_id == "belgian_pro_league:2026-27:2026-10-16"
        assert repository.list_for_scope("belgian_pro_league:2026-27:2026-10-09") == ()
        records = repository.list_for_scope("belgian_pro_league:2026-27:2026-10-16")
        assert len(records) == 1
        assert records[0].artifact_digest == recorded.artifact_digest


def test_instant_observation_local_date_must_match_the_league_timezone() -> None:
    with pytest.raises(ValueError, match="local date"):
        replace(_instant_observation(), source_local_date="2026-10-08")


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"official_url": "https://example.com/calendar"}, "approved Pro League"),
        ({"official_url": "https://proleague.be.evil.example/calendar"}, "approved Pro League"),
        (
            {
                "official_url": "https://www.proleague.be/nieuws/unrelated-article",
                "publication_id": "unrelated-article",
                "publication_type": "NEWS_ARTICLE",
            },
            "not approved",
        ),
        ({"season": "2025-26"}, "policy supports"),
        ({"league_key": "premier_league"}, "policy supports"),
        ({"status": "UNKNOWN"}, "status"),
        ({"kickoff": "2026-10-09T20:00:00"}, "UTC offset"),
        ({"kickoff": "tomorrow at eight"}, "ISO-8601"),
        ({"publication_date": "2026-02-30"}, "Publication date"),
        ({"title": "\nforged title"}, "control text"),
    ),
)
def test_record_refuses_unapproved_or_malformed_observation_inputs(
    tmp_path: Path,
    changes: dict[str, str],
    reason: str,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)

        with pytest.raises(ValueError, match=reason):
            repository.record(_valid_input(**changes))

        assert len(FixtureHistoryImporter(store, private_root=private_root).fixtures()) == 0


def test_record_refuses_unknown_ambiguous_and_same_team_without_registering_teams(
    tmp_path: Path,
) -> None:
    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(
            store,
            ("Synthetic North FC", "Synthetic South FC", "Synthetic East FC"),
        )
        league_id = deterministic_identifier("league", "belgian_pro_league")
        with store.transaction() as tx:
            for team_name in ("Synthetic North FC", "Synthetic East FC"):
                team_id = deterministic_identifier(
                    "team", f"belgian_pro_league:{canonical_key(team_name)}"
                )
                alias_id = deterministic_identifier(
                    "test_team_alias", f"{team_id}:Shared Synthetic Club"
                )
                tx.add_identifier_if_missing(CanonicalIdentifier("team_alias", alias_id))
                tx.execute(
                    """
                    INSERT INTO team_aliases (
                        alias_id, league_id, team_id, source_id, alias_name,
                        normalized_alias, mapping_rule_version, created_at_utc
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        alias_id,
                        league_id,
                        team_id,
                        "Shared Synthetic Club",
                        canonical_key("Shared Synthetic Club"),
                        "test-reviewed-alias-v1",
                        "2026-09-01T00:00:00+00:00",
                    ),
                )
        repository = OperatorFixtureObservationRepository(store, private_root=private_root)
        team_count_before = (
            store._connection_for_repository().execute("SELECT count(*) FROM teams").fetchone()[0]
        )

        with pytest.raises(ValueError, match="unknown"):
            repository.record(_valid_input(home="Unknown Synthetic Club"))
        with pytest.raises(ValueError, match="ambiguous"):
            repository.record(_valid_input(home="Shared Synthetic Club"))
        with pytest.raises(ValueError, match="different canonical teams"):
            repository.record(_valid_input(home="Synthetic North FC", away="Synthetic North FC"))

        team_count_after = (
            store._connection_for_repository().execute("SELECT count(*) FROM teams").fetchone()[0]
        )
        assert team_count_after == team_count_before == 3
        assert len(FixtureHistoryImporter(store, private_root=private_root).source_captures()) == 0


def test_cli_records_and_lists_one_explicit_scope_compactly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "cli-isolated-store"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))

    common = [
        "fixtures",
        "observe",
        "official",
        "record",
        "--store",
        str(database_path),
        "--league",
        "belgian_pro_league",
        "--season",
        "2026-27",
        "--friday",
        "2026-10-09",
        "--home",
        "Synthetic North FC",
        "--away",
        "Synthetic South FC",
        "--kickoff",
        "2026-10-09T20:00:00+02:00",
        "--status",
        "SCHEDULED",
        "--official-url",
        "https://www.proleague.be/jpl-kalender!",
        "--publication-id",
        "jpl-kalender",
        "--publication-type",
        "OFFICIAL_COMPETITION_CALENDAR",
        "--title",
        "Synthetic test citation",
        "--publication-date",
        "2026-09-29",
        "--operator-id",
        "operator-cli-test",
        "--json",
    ]
    assert main(common) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["mode"] == "RESEARCH_ONLY"
    assert recorded["scope_id"] == "belgian_pro_league:2026-27:2026-10-09"
    assert recorded["resolved_fixture"] == "Synthetic North FC vs Synthetic South FC"
    assert recorded["kickoff_utc"] == "2026-10-09T18:00:00+00:00"
    assert recorded["status"] == "SCHEDULED"
    assert len(recorded) == 9
    assert "home_team_id" not in recorded

    assert (
        main(
            [
                "fixtures",
                "observe",
                "official",
                "list",
                "--store",
                str(database_path),
                "--league",
                "belgian_pro_league",
                "--season",
                "2026-27",
                "--friday",
                "2026-10-09",
                "--json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["scope_id"] == recorded["scope_id"]
    assert len(listed["observations"]) == 1
    assert listed["observations"][0]["artifact_digest"] == recorded["artifact_digest"]

    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "fixtures",
                "observe",
                "official",
                "record",
                "--league",
                "belgian_pro_league",
                "--season",
                "2026-27",
                "--friday",
                "2026-10-09",
                "--home",
                "Synthetic North FC",
                "--away",
                "Synthetic South FC",
                "--kickoff",
                "2026-10-09",
                "--status",
                "SCHEDULED",
                "--official-url",
                "https://www.proleague.be/jpl-kalender!",
                "--publication-id",
                "jpl-kalender",
                "--publication-type",
                "OFFICIAL_COMPETITION_CALENDAR",
                "--title",
                "Synthetic test citation",
                "--operator-id",
                "operator-cli-test",
            ]
        )


def test_fresh_acquisition_includes_only_exact_manual_scope_without_promoting_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet import operator_fixture_attestation_cli
    from matchvet.matchweek_membership import MatchweekMembershipError
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.operator_fixture_attestation_cli import handle_fixture_attestation
    from matchvet.provider_health import ProviderAttemptReference
    from matchvet.provider_health_repository import ProviderHealthRepository

    private_root, store_context = _open_observation_store(tmp_path)
    with store_context as store:
        _seed_belgian_teams(
            store,
            (
                "Synthetic North FC",
                "Synthetic South FC",
                "Synthetic East FC",
                "Synthetic West FC",
            ),
        )
        scopes = fixture_scopes_for_matchweek("2026-10-09", season="2026-27")
        old_assessment = assess_fixture_coverage(
            scopes=scopes,
            provider_attempts=(),
            coverage_evidence=(),
            fixture_revisions=(),
            identity_resolutions=(),
            freshness_results=(),
        )
        fixture_repository = FixtureCoverageRepository(store)
        fixture_repository.persist(old_assessment)
        old_payload = (
            store._connection_for_repository()
            .execute(
                "SELECT assessment_json FROM fixture_coverage_assessments "
                "WHERE assessment_digest = ?",
                (old_assessment.digest,),
            )
            .fetchone()[0]
        )

        observations = OperatorFixtureObservationRepository(store, private_root=private_root)
        first = observations.record(
            _valid_input(
                home="Synthetic North FC",
                away="Synthetic South FC",
                title="Synthetic matchweek fixture A",
            )
        )
        second = observations.record(
            _valid_input(
                home="Synthetic East FC",
                away="Synthetic West FC",
                kickoff="2026-10-10T18:00:00+02:00",
                title="Synthetic matchweek fixture B",
            )
        )
        other_matchweek = observations.record(
            _valid_input(
                friday="2026-10-16",
                home="Synthetic North FC",
                away="Synthetic East FC",
                kickoff="2026-10-16T20:00:00+02:00",
                title="Synthetic different matchweek fixture",
            )
        )

        importer = FixtureHistoryImporter(store, private_root=private_root)
        scheduled = FixtureHistoryAcquirer(
            importer, StaticSourceFetcher({})
        ).acquire_scheduled_fixtures(
            IngestionPlan(current_season="2026-27", matchweek_friday="2026-10-09")
        )
        assessment = scheduled.assessment
        bel_scope = next(
            item
            for item in assessment.scope_assessments
            if item.scope.league_key == "belgian_pro_league"
        )
        assert len(assessment.provider_attempts) == 12
        assert len(bel_scope.provider_attempt_ids) == 0
        assert assessment.coverage_evidence == ()
        assert bel_scope.coverage_state is ScopeCoverageState.UNKNOWN
        assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN
        assert len(assessment.fixture_revisions) == 2
        assert {item.fixture_id for item in assessment.fixture_revisions} == {
            first.fixture_id,
            second.fixture_id,
        }
        assert other_matchweek.fixture_id not in {
            item.fixture_id for item in assessment.fixture_revisions
        }
        assert {
            scope.scope.league_key: len(scope.provider_attempt_ids)
            for scope in assessment.scope_assessments
            if scope.scope.league_key != "belgian_pro_league"
        } == {
            "premier_league": 2,
            "serie_a": 2,
            "la_liga": 2,
            "bundesliga": 2,
            "ligue_1": 2,
            "liga_portugal": 2,
        }

        stored_old = fixture_repository.get(old_assessment.digest)
        old_payload_after = (
            store._connection_for_repository()
            .execute(
                "SELECT assessment_json FROM fixture_coverage_assessments "
                "WHERE assessment_digest = ?",
                (old_assessment.digest,),
            )
            .fetchone()[0]
        )
        assert stored_old == old_assessment
        assert old_payload_after == old_payload
        assert bel_scope.coverage_state is ScopeCoverageState.UNKNOWN
        assert {item.provider_id for item in assessment.provider_attempts}.isdisjoint(
            {"manual-citation", "operator-official-fixture-observation"}
        )

        manifest = fixture_repository.build_candidate_manifest(
            assessment, "belgian_pro_league:2026-27:2026-10-09"
        )
        assert manifest.candidate_count == 2
        assert {item.canonical_fixture_id for item in manifest.entries} == {
            first.fixture_id,
            second.fixture_id,
        }
        assert all(
            any(item.predicate == "fixture_status" for item in entry.assertion_facts)
            for entry in manifest.entries
        )
        assert {
            capture_id for entry in manifest.entries for capture_id in entry.source_capture_ids
        } == {first.capture_id, second.capture_id}

        monkeypatch.setattr(
            operator_fixture_attestation_cli,
            "termux_private_root",
            lambda: private_root,
        )
        prepare = _parser().parse_args(
            [
                "fixtures",
                "attest",
                "prepare",
                "--base",
                assessment.digest,
                "--league",
                "belgian_pro_league",
                "--season",
                "2026-27",
                "--friday",
                "2026-10-09",
                "--store",
                str(store.path),
                "--json",
            ]
        )
        health = ProviderHealthRepository(store).list_for_assessment(assessment.digest)
        assert len(health) == len(assessment.provider_attempts) == 12
        health_attempt_ids = {
            reference.attempt_id
            for record in health
            for reference in record.provenance
            if isinstance(reference, ProviderAttemptReference)
        }
        assert health_attempt_ids == {item.attempt_id for item in assessment.provider_attempts}
        assert all(
            item.provider.provider_id != "operator-official-fixture-observation" for item in health
        )

        with pytest.raises(MatchweekMembershipError) as refusal:
            MatchweekMembershipRepository(store).freeze_exact(
                "2026-27",
                "2026-10-09",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )
        assert refusal.value.reason_code == "ASSESSMENT_INCOMPLETE"

        store.close()
        assert handle_fixture_attestation(prepare) == 0
        prepared = json.loads(capsys.readouterr().out)
        assert prepared["candidate_count"] == 2
        assert {item["canonical_fixture_id"] for item in prepared["entries"]} == {
            first.fixture_id,
            second.fixture_id,
        }


def test_t17_backup_and_restore_preserve_observation_artifact_and_fixture_provenance(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "source-isolated-store"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        _seed_belgian_teams(store, ("Synthetic North FC", "Synthetic South FC"))
        recorded = OperatorFixtureObservationRepository(store, private_root=private_root).record(
            _valid_input()
        )

    resource_observation = ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )
    backup_path = tmp_path / "shared-lf05-backup"
    result = backup_store(
        database_path,
        backup_path,
        private_root=private_root,
        resource_observation=resource_observation,
    )
    assert result.status == "COMPLETE"
    assert verify_backup(backup_path).verified

    restored_root = tmp_path / "restored-isolated-store"
    restored_path = restored_root / "matchvet.sqlite3"
    restored = restore_backup(
        backup_path,
        restored_path,
        private_root=restored_root,
        resource_observation=resource_observation,
    )
    assert restored.status == "COMPLETE"
    with open_store(restored_path, private_root=restored_root) as store:
        replayed = OperatorFixtureObservationRepository(store, private_root=restored_root).get(
            recorded.artifact_digest
        )
        importer = FixtureHistoryImporter(store, private_root=restored_root)
        assert replayed.observation == recorded.observation
        assert replayed.capture_id == recorded.capture_id
        assert replayed.fixture_id == recorded.fixture_id
        assert replayed.revision_id == recorded.revision_id
        assert len(importer.source_assertions()) == 4
        assert len(importer.revisions(recorded.fixture_id)) == 1
        assert ArtifactStore(store).object_root == restored_root / "objects" / "sha256"

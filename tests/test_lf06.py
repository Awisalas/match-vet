"""LF06 regressions for shared current-database team identity resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from matchvet.ingestion import (
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    FootballDataCSVParser,
    ImportResult,
    IngestionPlan,
    MappingState,
    OpenFootballJSONParser,
    SourceCaptureInput,
    SourceKind,
    StaticSourceFetcher,
    TeamIdentityPolicy,
    canonical_key,
    deterministic_identifier,
    football_data_url,
    league_by_key,
    openfootball_text_url,
    openfootball_url,
)
from matchvet.store import CanonicalIdentifier, Store, open_store
from matchvet.team_alias_registry import default_registry

_SERIE_A_REVIEWED_TEAMS = (
    ("Fiorentina", "ACF Fiorentina", "15f1e37e-7e97-562e-951c-c881321a0592"),
    ("Roma", "AS Roma", "2876aa97-fd00-5433-ae45-7d2c95113d1e"),
    ("Atalanta", "Atalanta BC", "44e329de-5758-5bac-9cf1-d0f778fe36e3"),
    ("Bologna", "Bologna FC 1909", "fc746cac-1c0f-5fa7-93c4-78970d7d223c"),
    ("Cagliari", "Cagliari Calcio", "3a913936-7c05-553a-80ff-f41546d29aaf"),
    ("Como", "Como 1907", "71cdfd16-58ef-5eac-a010-cf0845f3349e"),
    ("Inter", "FC Internazionale Milano", "80cf1b85-f7bc-5ed5-9494-69a916d69b76"),
    ("Genoa", "Genoa CFC", "1bb95ff8-c591-58d5-8054-5544c3d3745e"),
    ("Parma", "Parma Calcio 1913", "e3124fdd-d515-59fb-a24a-bfc821aa090e"),
    ("Napoli", "SSC Napoli", "f32eb93a-88de-5c7c-a2a8-216bf383fc2c"),
    ("Lecce", "US Lecce", "149ae96b-da42-5a4c-8bf2-14904e71ed6c"),
    ("Sassuolo", "US Sassuolo Calcio", "85ea2339-736f-5fda-9323-71821ca4b167"),
    ("Udinese", "Udinese Calcio", "d58ca08f-dfbd-5cef-8c6a-029b39d8672d"),
)


def _serie_a_history_csv() -> bytes:
    names = [canonical for canonical, _source, _team_id in _SERIE_A_REVIEWED_TEAMS]
    rows = ["Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR"]
    rows.extend(
        f"I1,21/08/2025,20:00,{home},{away},1,0,H"
        for home, away in zip(names, (*names[1:], names[0]), strict=True)
    )
    return ("\n".join(rows) + "\n").encode()


def _serie_a_openfootball_json() -> bytes:
    spellings = [source for _canonical, source, _team_id in _SERIE_A_REVIEWED_TEAMS]
    return json.dumps(
        {
            "matches": [
                {
                    "date": "2026-08-21",
                    "time": "20:00",
                    "team1": home,
                    "team2": away,
                    "score": {"ft": [1, 0]},
                }
                for home, away in zip(spellings, (*spellings[1:], spellings[0]), strict=True)
            ]
        },
        ensure_ascii=False,
    ).encode()


def _mapping_rows(store: Store) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in store._connection_for_repository()
        .execute(
            """SELECT source_id, league_id, source_team_key, source_team_name,
                      mapping_state, team_id, candidates_json, mapping_rule_version
               FROM source_team_mappings ORDER BY source_id, league_id, source_team_key"""
        )
        .fetchall()
    )


def _team_rows(store: Store) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in store._connection_for_repository()
        .execute(
            "SELECT team_id, league_id, canonical_name, normalized_name FROM teams ORDER BY team_id"
        )
        .fetchall()
    )


def _seed_teams(store: Store, league_key: str, names: tuple[str, ...]) -> None:
    league = league_by_key(league_key)
    league_id = deterministic_identifier("league", league.key)
    created_at = "2026-09-29T00:00:00+00:00"
    with store.transaction() as tx:
        tx.add_identifier_if_missing(CanonicalIdentifier("league", league_id))
        tx.execute(
            """INSERT INTO target_leagues (
                league_id, league_key, canonical_name, country, football_data_code,
                openfootball_code, source_timezone, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(league_id) DO NOTHING""",
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
                """INSERT INTO teams (
                    team_id, league_id, canonical_name, normalized_name, created_at_utc
                ) VALUES (?, ?, ?, ?, ?) ON CONFLICT(team_id) DO NOTHING""",
                (team_id, league_id, name, canonical_key(name), created_at),
            )


def _openfootball_json(
    importer: FixtureHistoryImporter,
    league_key: str,
    season: str,
    home: str,
    away: str,
    *,
    identity_policy: TeamIdentityPolicy = TeamIdentityPolicy.REGISTER_UNKNOWN,
    cache_key: str | None = None,
    retrieved_at_utc: str = "2026-09-29T12:00:00+00:00",
) -> tuple[bytes, ImportResult]:
    league = league_by_key(league_key)
    content = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-10-09",
                    "time": "20:00",
                    "team1": home,
                    "team2": away,
                    "score": {},
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
    result = importer.import_dataset(
        OpenFootballJSONParser().parse(content, league=league, season=season),
        content,
        SourceCaptureInput(
            source_url=openfootball_url(league, season),
            retrieved_at_utc=retrieved_at_utc,
            observed_terms="OpenFootball CC0",
            cache_key=cache_key,
        ),
        identity_policy=identity_policy,
    )
    return content, result


def test_register_unknown_reuses_reviewed_teams_after_football_data_import(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("serie_a")
    history = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"I1,21/08/2025,20:00,Fiorentina,Roma,1,0,H\n"
    )
    schedule = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-10-09",
                    "time": "20:00",
                    "team1": "ACF Fiorentina",
                    "team2": "AS Roma",
                    "score": {},
                }
            ]
        }
    ).encode()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        importer.import_dataset(
            FootballDataCSVParser().parse(history, league=league, season="2025-26"),
            history,
            SourceCaptureInput(
                source_url=football_data_url(league, "2025-26"),
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )
        schedule_result = importer.import_dataset(
            OpenFootballJSONParser().parse(schedule, league=league, season="2026-27"),
            schedule,
            SourceCaptureInput(
                source_url=openfootball_url(league, "2026-27"),
                retrieved_at_utc="2026-09-29T12:05:00+00:00",
                observed_terms="OpenFootball CC0",
            ),
        )

        historical = next(item for item in importer.fixtures() if item.season == "2025-26")
        current = next(item for item in importer.fixtures() if item.season == "2026-27")
        assert (historical.home_team_id, historical.away_team_id) == (
            "15f1e37e-7e97-562e-951c-c881321a0592",
            "2876aa97-fd00-5433-ae45-7d2c95113d1e",
        )
        assert (current.home_team_id, current.away_team_id) == (
            historical.home_team_id,
            historical.away_team_id,
        )
        assert schedule_result.unresolved_rows == 0


def test_register_unknown_seeds_missing_reviewed_frosinone_target_without_alias(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Existing Club",))
        importer = FixtureHistoryImporter(store, private_root=private_root)
        content, result = _openfootball_json(
            importer, "serie_a", "2026-27", "Frosinone Calcio", "Existing Club"
        )

        fixture = next(item for item in importer.fixtures() if item.season == "2026-27")
        mapping = (
            store._connection_for_repository()
            .execute(
                """SELECT team_id, mapping_rule_version FROM source_team_mappings
               WHERE source_team_name = 'Frosinone Calcio'"""
            )
            .fetchone()
        )
        registry = default_registry()
        aliases = (
            store._connection_for_repository()
            .execute("SELECT alias_name FROM team_aliases WHERE alias_name = 'Frosinone Calcio'")
            .fetchall()
        )

        assert result.unresolved_rows == 0
        assert fixture.home_team_id == "d463f5bd-51b2-56ac-aa9f-cda1e896379a"
        assert fixture.home_team_name == "Frosinone"
        assert tuple(mapping) == (
            fixture.home_team_id,
            f"{registry.version}:{registry.digest}",
        )
        assert aliases == []
        scheduled = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {
                    openfootball_url(league_by_key("serie_a"), "2026-27"): content + b"\n",
                    openfootball_text_url(
                        league_by_key("serie_a"), "2026-27"
                    ): b"= Italy Serie A 2026/27\n\nMatchday 1\n\nFri Oct 9 2026\n\n"
                    b"20:00 Frosinone Calcio v Existing Club\n",
                },
                retrieved_at_utc="2026-09-29T12:10:00+00:00",
            ),
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league_by_key("serie_a"),),
                matchweek_friday="2026-10-09",
            )
        )
        assert any(
            resolution.canonical_fixture_id == fixture.fixture_id
            for resolution in scheduled.assessment.identity_resolutions
        )
        assert {
            item.canonical_team_id
            for item in (
                importer.resolve_existing_team(
                    league_by_key("serie_a"),
                    "2026-27",
                    "Frosinone Calcio",
                    source_kind=SourceKind.OPENFOOTBALL,
                ),
                importer.resolve_existing_team(
                    league_by_key("serie_a"),
                    "2026-27",
                    "Frosinone Calcio",
                    source_kind=SourceKind.OPENFOOTBALL_TEXT,
                ),
            )
        } == {fixture.home_team_id}


def test_known_only_leaves_missing_reviewed_frosinone_target_unresolved(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Existing Club",))
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(
            importer,
            "serie_a",
            "2026-27",
            "Frosinone Calcio",
            "Existing Club",
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )

        team_names = (
            store._connection_for_repository()
            .execute("SELECT canonical_name FROM teams ORDER BY canonical_name")
            .fetchall()
        )
        assert result.unresolved_rows == 1
        assert importer.fixtures() == ()
        assert [str(row[0]) for row in team_names] == ["Existing Club"]


@pytest.mark.parametrize(
    "policy",
    (TeamIdentityPolicy.KNOWN_ONLY, TeamIdentityPolicy.REGISTER_UNKNOWN),
)
def test_missing_reviewed_frosinone_target_does_not_override_a_direct_identity(
    tmp_path: Path,
    policy: TeamIdentityPolicy,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Frosinone Calcio", "Existing Club"))
        before = (
            store._connection_for_repository()
            .execute("SELECT team_id, canonical_name FROM teams ORDER BY team_id")
            .fetchall()
        )
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(
            importer,
            "serie_a",
            "2026-27",
            "Frosinone Calcio",
            "Existing Club",
            identity_policy=policy,
        )

        connection = store._connection_for_repository()
        after = connection.execute(
            "SELECT team_id, canonical_name FROM teams ORDER BY team_id"
        ).fetchall()
        registry_target = connection.execute(
            "SELECT 1 FROM teams WHERE team_id = ?",
            ("d463f5bd-51b2-56ac-aa9f-cda1e896379a",),
        ).fetchone()
        assert result.unresolved_rows == 1
        assert importer.fixtures() == ()
        assert after == before
        assert registry_target is None


@pytest.mark.parametrize("first_source", ("football_data", "openfootball"))
def test_serie_a_acquisition_order_resolves_all_reviewed_teams_without_duplicates(
    tmp_path: Path, first_source: str
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("serie_a")
    history = _serie_a_history_csv()
    schedule = _serie_a_openfootball_json()
    history_plan = IngestionPlan(
        current_season="2025-26", leagues=(league,), use_openfootball_fallback=False
    )
    current_plan = IngestionPlan(current_season="2026-27", leagues=(league,))
    registry = default_registry()
    expected_teams = {
        team_id: canonical_name for canonical_name, _source_name, team_id in _SERIE_A_REVIEWED_TEAMS
    }

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)

        def import_history() -> None:
            report = FixtureHistoryAcquirer(
                importer,
                StaticSourceFetcher(
                    {football_data_url(league, "2025-26"): history},
                    retrieved_at_utc="2026-09-29T12:00:00+00:00",
                ),
            ).acquire(history_plan)
            assert len(report.imports) == 1
            assert report.imports[0].unresolved_rows == 0
            assert report.issues == ()

        def import_current_schedule() -> None:
            report = FixtureHistoryAcquirer(
                importer,
                StaticSourceFetcher(
                    {openfootball_url(league, "2026-27"): schedule},
                    retrieved_at_utc="2026-09-29T12:05:00+00:00",
                ),
            ).acquire(current_plan)
            assert len(report.imports) == 1
            assert report.fallback_imports == 1
            assert report.imports[0].unresolved_rows == 0
            assert report.issues == ()

        if first_source == "football_data":
            import_history()
            import_current_schedule()
        else:
            import_current_schedule()
            import_history()

        connection = store._connection_for_repository()
        actual_teams = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                """SELECT team_id, canonical_name FROM teams
                   WHERE league_id = ? ORDER BY team_id""",
                (deterministic_identifier("league", league.key),),
            ).fetchall()
        }
        expected_mapping_rows = connection.execute(
            """SELECT source_team_name, mapping_state, team_id, mapping_rule_version
               FROM source_team_mappings
               WHERE source_id = ? AND league_id = ? ORDER BY source_team_name""",
            (
                deterministic_identifier("source", "openfootball"),
                deterministic_identifier("league", league.key),
            ),
        ).fetchall()
        source_names = {
            source_name for _canonical, source_name, _team_id in _SERIE_A_REVIEWED_TEAMS
        }
        mappings = {
            str(row[0]): (str(row[1]), str(row[2]), str(row[3])) for row in expected_mapping_rows
        }
        global_alias_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT alias_name FROM team_aliases WHERE league_id = ?",
                (deterministic_identifier("league", league.key),),
            ).fetchall()
        }
        assert actual_teams == expected_teams
        assert set(mappings) == source_names
        assert mappings == {
            source_name: (
                MappingState.CONFIRMED.value,
                team_id,
                f"{registry.version}:{registry.digest}",
            )
            for _canonical, source_name, team_id in _SERIE_A_REVIEWED_TEAMS
        }
        assert source_names.isdisjoint(global_alias_names)
        assert len(importer.fixtures()) == 26
        assert len({item.fixture_id for item in importer.fixtures()}) == 26

        stable_teams = _team_rows(store)
        stable_mappings = _mapping_rows(store)
        replay = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {openfootball_url(league, "2026-27"): schedule},
                retrieved_at_utc="2026-09-29T12:05:00+00:00",
            ),
        ).acquire(current_plan)
        assert replay.imports[0].from_existing_capture is True
        assert _team_rows(store) == stable_teams
        assert _mapping_rows(store) == stable_mappings


def test_same_clubs_meeting_across_sources_keep_one_fixture_identity(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("serie_a")
    history = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"I1,09/10/2026,20:00,Fiorentina,Roma,1,0,H\n"
    )
    schedule = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-10-09",
                    "time": "20:00",
                    "team1": "ACF Fiorentina",
                    "team2": "AS Roma",
                    "score": {"ft": [1, 0]},
                }
            ]
        }
    ).encode()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        football_data_result = importer.import_dataset(
            FootballDataCSVParser().parse(history, league=league, season="2026-27"),
            history,
            SourceCaptureInput(
                source_url=football_data_url(league, "2026-27"),
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )
        openfootball_result = importer.import_dataset(
            OpenFootballJSONParser().parse(schedule, league=league, season="2026-27"),
            schedule,
            SourceCaptureInput(
                source_url=openfootball_url(league, "2026-27"),
                retrieved_at_utc="2026-09-29T12:05:00+00:00",
                observed_terms="OpenFootball CC0",
            ),
        )

        football_data_observation = importer.observations_for_capture(
            football_data_result.source_capture_id
        )[0]
        openfootball_observation = importer.observations_for_capture(
            openfootball_result.source_capture_id
        )[0]
        assert football_data_observation.fixture_id is not None
        assert openfootball_observation.fixture_id == football_data_observation.fixture_id
        assert len(importer.fixtures()) == 1


def test_unique_persisted_alias_resolves_through_register_unknown(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Existing Club", "Other Club"))
        league_id = deterministic_identifier("league", "serie_a")
        team_id = deterministic_identifier("team", "serie_a:existing club")
        alias_id = deterministic_identifier("team_alias", f"serie_a:{team_id}:the existing club")
        with store.transaction() as tx:
            tx.add_identifier_if_missing(CanonicalIdentifier("team_alias", alias_id))
            tx.execute(
                """INSERT INTO team_aliases (
                    alias_id, league_id, team_id, source_id, alias_name, normalized_alias,
                    mapping_rule_version, created_at_utc
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    alias_id,
                    league_id,
                    team_id,
                    "The Existing Club",
                    canonical_key("The Existing Club"),
                    "test-confirmed-alias-v1",
                    "2026-09-29T00:00:00+00:00",
                ),
            )
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(
            importer, "serie_a", "2026-27", "The Existing Club", "Other Club"
        )
        assert result.unresolved_rows == 0
        fixture = importer.fixtures()[0]
        assert fixture.home_team_id == team_id
        mapping = (
            store._connection_for_repository()
            .execute(
                """SELECT mapping_state, team_id FROM source_team_mappings
                   WHERE source_team_name = ?""",
                ("The Existing Club",),
            )
            .fetchone()
        )
        assert tuple(mapping) == (MappingState.CONFIRMED.value, team_id)


def test_injected_registry_is_revalidated_before_import(tmp_path: Path) -> None:
    from dataclasses import replace

    from matchvet.team_alias_registry import TeamAliasRegistry

    private_root = tmp_path / "private"
    private_root.mkdir()
    registry = default_registry()
    invalid_registry = TeamAliasRegistry(
        version=registry.version,
        digest=registry.digest,
        entries=(
            replace(registry.entries[0], team_id="00000000-0000-7000-8000-000000000000"),
            *registry.entries[1:],
        ),
    )
    with (
        open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store,
        pytest.raises(ValueError, match="digest mismatch"),
    ):
        FixtureHistoryImporter(
            store,
            private_root=private_root,
            team_alias_registry=invalid_registry,
        )


def test_persisted_alias_and_registry_conflict_persists_ambiguity(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Fiorentina", "Roma"))
        league_id = deterministic_identifier("league", "serie_a")
        roma_id = deterministic_identifier("team", "serie_a:roma")
        alias_id = deterministic_identifier(
            "team_alias",
            f"serie_a:15f1e37e-7e97-562e-951c-c881321a0592:{canonical_key('ACF Fiorentina')}",
        )
        with store.transaction() as tx:
            tx.add_identifier_if_missing(CanonicalIdentifier("team_alias", alias_id))
            tx.execute(
                """INSERT INTO team_aliases (
                    alias_id, league_id, team_id, source_id, alias_name, normalized_alias,
                    mapping_rule_version, created_at_utc
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    alias_id,
                    league_id,
                    roma_id,
                    "ACF Fiorentina",
                    canonical_key("ACF Fiorentina"),
                    "test-conflicting-alias-v1",
                    "2026-09-29T00:00:00+00:00",
                ),
            )
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(importer, "serie_a", "2026-27", "ACF Fiorentina", "Roma")
        connection = store._connection_for_repository()
        mapping = connection.execute(
            """SELECT mapping_state, team_id, candidates_json
               FROM source_team_mappings WHERE source_team_name = 'ACF Fiorentina'"""
        ).fetchone()
        assert result.unresolved_rows == 1
        assert tuple(mapping) == (
            MappingState.AMBIGUOUS.value,
            None,
            json.dumps(
                ["15f1e37e-7e97-562e-951c-c881321a0592", roma_id],
                separators=(",", ":"),
            ),
        )
        assert importer.fixtures() == ()


@pytest.mark.parametrize(
    ("policy", "expected_unresolved"),
    (
        (TeamIdentityPolicy.REGISTER_UNKNOWN, 0),
        (TeamIdentityPolicy.KNOWN_ONLY, 1),
    ),
)
def test_genuine_unknown_registration_respects_policy_and_frozen_id(
    tmp_path: Path, policy: TeamIdentityPolicy, expected_unresolved: int
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        _seed_teams(store, "serie_a", ("Known Club",))
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(
            importer,
            "serie_a",
            "2026-27",
            "Unknown Athletic",
            "Known Club",
            identity_policy=policy,
        )
        unknown_id = deterministic_identifier("team", "serie_a:unknown athletic")
        row = (
            store._connection_for_repository()
            .execute("SELECT team_id, canonical_name FROM teams WHERE team_id = ?", (unknown_id,))
            .fetchone()
        )
        assert result.unresolved_rows == expected_unresolved
        if policy is TeamIdentityPolicy.REGISTER_UNKNOWN:
            assert tuple(row) == ("2a91e956-0f85-593e-8a21-51518cdab921", "Unknown Athletic")
            mapping = (
                store._connection_for_repository()
                .execute(
                    """SELECT mapping_state, team_id, mapping_rule_version
                   FROM source_team_mappings WHERE source_team_name = 'Unknown Athletic'"""
                )
                .fetchone()
            )
            assert tuple(mapping) == (
                MappingState.CONFIRMED.value,
                unknown_id,
                "matchvet-t06-team-v1",
            )
        else:
            assert row is None
            assert importer.fixtures() == ()


def test_backup_restore_preserves_lf06_team_mappings(tmp_path: Path) -> None:
    from matchvet.runs import GIB, ResourceObservation
    from matchvet.t17 import backup_store, restore_backup

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        _, result = _openfootball_json(
            importer, "serie_a", "2026-27", "Frosinone Calcio", "Unknown Opponent"
        )
        assert result.unresolved_rows == 0
        expected_teams = _team_rows(store)
        expected_mappings = _mapping_rows(store)
        expected_aliases = tuple(
            tuple(row)
            for row in store._connection_for_repository()
            .execute(
                """SELECT alias_id, league_id, team_id, alias_name, normalized_alias
                   FROM team_aliases ORDER BY alias_id"""
            )
            .fetchall()
        )

    observation = ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )
    bundle = tmp_path / "shared" / "lf06-backup"
    backup = backup_store(
        database_path,
        bundle,
        private_root=private_root,
        resource_observation=observation,
    )
    restored_path = private_root / "restored" / "matchvet.sqlite3"
    restored = restore_backup(
        bundle,
        restored_path,
        private_root=private_root,
        resource_observation=observation,
    )
    assert backup.status == restored.status == "COMPLETE"
    with open_store(restored_path, private_root=private_root) as restored_store:
        assert _team_rows(restored_store) == expected_teams
        assert _mapping_rows(restored_store) == expected_mappings
        aliases = tuple(
            tuple(row)
            for row in restored_store._connection_for_repository()
            .execute(
                """SELECT alias_id, league_id, team_id, alias_name, normalized_alias
                   FROM team_aliases ORDER BY alias_id"""
            )
            .fetchall()
        )
        assert aliases == expected_aliases

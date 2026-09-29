"""LF03 scheduled identity regressions at the importer and acquirer boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from matchvet.ingestion import (
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    FootballDataCSVParser,
    IngestionPlan,
    MappingState,
    OpenFootballJSONParser,
    SourceCaptureInput,
    StaticSourceFetcher,
    TeamCanonicalizer,
    TeamIdentityPolicy,
    canonical_key,
    deterministic_identifier,
    football_data_url,
    league_by_key,
    openfootball_text_url,
    openfootball_url,
)
from matchvet.store import CanonicalIdentifier, Store, open_store
from matchvet.team_alias_registry import TeamAliasRegistry, default_registry


def _seed(store: Store, league_key: str, names: tuple[str, ...]) -> None:
    league = league_by_key(league_key)
    league_id = deterministic_identifier("league", league_key)
    now = "2026-09-29T00:00:00+00:00"
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
                now,
            ),
        )
        for name in names:
            team_id = deterministic_identifier("team", f"{league_key}:{canonical_key(name)}")
            tx.add_identifier_if_missing(CanonicalIdentifier("team", team_id))
            tx.execute(
                """INSERT INTO teams (team_id, league_id, canonical_name,
                normalized_name, created_at_utc) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO NOTHING""",
                (team_id, league_id, name, canonical_key(name), now),
            )


def _registry_with_update(original_name: str, **changes: str) -> TeamAliasRegistry:
    registry_path = Path(__file__).parents[1] / "src/matchvet/team_alias_registry_v1.json"
    payload = json.loads(registry_path.read_text())
    entry = next(item for item in payload["entries"] if item["source_name"] == original_name)
    entry.update(changes)
    payload["entries"].sort(
        key=lambda item: (
            item["league_key"],
            item["season"],
            item["source_lineage"],
            item["normalized_name"],
        )
    )
    digest_payload = {"version": payload["version"], "entries": payload["entries"]}
    payload["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                digest_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()
    )
    return TeamAliasRegistry.from_json(json.dumps(payload).encode())


def _add_alias(store: Store, league_key: str, alias_name: str, target_name: str) -> None:
    league_id = deterministic_identifier("league", league_key)
    team_id = deterministic_identifier("team", f"{league_key}:{canonical_key(target_name)}")
    alias_id = deterministic_identifier(
        "team_alias", f"{league_key}:{team_id}:{canonical_key(alias_name)}"
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
                team_id,
                alias_name,
                canonical_key(alias_name),
                "test-confirmed-alias-v1",
                "2026-09-29T12:00:00+00:00",
            ),
        )


def _import_json(
    importer: FixtureHistoryImporter,
    league_key: str,
    season: str,
    home: str,
    away: str,
) -> tuple[MappingState, str | None]:
    league = league_by_key(league_key)
    content = json.dumps(
        {
            "matches": [
                {"date": "2026-10-09", "time": "20:00", "team1": home, "team2": away, "score": {}}
            ]
        },
        ensure_ascii=False,
    ).encode()
    result = importer.import_dataset(
        OpenFootballJSONParser().parse(content, league=league, season=season),
        content,
        SourceCaptureInput(
            source_url=openfootball_url(league, season),
            retrieved_at_utc="2026-09-29T12:00:00+00:00",
            observed_terms="OpenFootball CC0",
        ),
        identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
    )
    observation = importer.observations_for_capture(result.source_capture_id)[0]
    state = MappingState.CONFIRMED if observation.fixture_id else MappingState.UNKNOWN
    return state, observation.fixture_id


def _different_opponent(
    name: str,
    league_key: str,
    first: dict[str, str],
    second: dict[str, str],
    registry: TeamAliasRegistry,
) -> str:
    matching = registry.candidates(league_key, "2026-27", "openfootball-schedule", name)
    resolved_id = (
        matching[0].team_id
        if matching
        else deterministic_identifier("team", f"{league_key}:{canonical_key(name)}")
    )
    return second["canonical_name"] if resolved_id == first["team_id"] else first["canonical_name"]


def test_canonical_names_resolve_after_importer_construction(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        importer = FixtureHistoryImporter(store, private_root=root)
        _seed(store, "premier_league", ("Arsenal FC", "Chelsea FC"))
        state, fixture_id = _import_json(
            importer, "premier_league", "2026-27", "Arsenal FC", "Chelsea FC"
        )
        assert state is MappingState.CONFIRMED
        assert fixture_id == "356de3d9-e504-5ea1-b295-33b1c177f7af"
        assert len(importer.fixtures()) == 1


def test_known_only_does_not_persist_an_in_memory_only_team(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("premier_league")
    canonicalizer = TeamCanonicalizer()
    canonicalizer.register_team(league, "Unpersisted United")
    content = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-10-09",
                    "time": "20:00",
                    "team1": "Unpersisted United",
                    "team2": "Unknown Athletic",
                    "score": {},
                }
            ]
        }
    ).encode()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        importer = FixtureHistoryImporter(
            store, private_root=root, team_canonicalizer=canonicalizer
        )
        result = importer.import_dataset(
            OpenFootballJSONParser().parse(content, league=league, season="2026-27"),
            content,
            SourceCaptureInput(
                source_url=openfootball_url(league, "2026-27"),
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
                observed_terms="OpenFootball CC0",
            ),
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        assert result.unresolved_rows == 1
        assert (
            store._connection_for_repository().execute("SELECT COUNT(*) FROM teams").fetchone()[0]
            == 0
        )


def test_current_feed_upcoming_rows_cannot_create_teams_before_schedule(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("premier_league")
    _season = "2026-27"
    football_data = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"E0,10/10/2026,15:00,Unlisted FC,Arsenal FC,,,\n"
        b"E0,10/10/2026,17:00,Arsenal FC,Chelsea FC,,,\n"
    )
    schedule = (
        b'{"matches":['
        b'{"date":"2026-10-10","time":"15:00",'
        b'"team1":"Unlisted FC","team2":"Arsenal FC","score":{}},'
        b'{"date":"2026-10-10","time":"17:00",'
        b'"team1":"Arsenal FC","team2":"Chelsea FC","score":{}}]}'
    )
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, league.key, ("Arsenal FC", "Chelsea FC"))
        importer = FixtureHistoryImporter(store, private_root=root)
        report = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {
                    football_data_url(league, _season): football_data,
                    openfootball_url(league, _season): schedule,
                },
                retrieved_at_utc="2026-10-01T12:00:00+00:00",
            ),
        ).acquire(
            IngestionPlan(
                current_season=_season,
                leagues=(league,),
                matchweek_friday="2026-10-09",
            )
        )
        assert report.scheduled_fixtures is not None
        assert report.scheduled_fixtures.imports[0].unresolved_rows == 1
        resolved = [
            identity
            for identity in report.scheduled_fixtures.assessment.identity_resolutions
            if identity.canonical_fixture_id is not None
        ]
        assert len(resolved) == 1
        assert len(resolved[0].source_capture_ids) == 1
        assert (
            store._connection_for_repository()
            .execute("SELECT COUNT(*) FROM teams WHERE canonical_name = 'Unlisted FC'")
            .fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Coventry City FC", "coventry"),
        ("Leeds United FC", "leeds"),
        ("West Ham United FC", "west ham"),
        ("Manchester United FC", "man united"),
        ("Manchester City FC", "man city"),
        ("Tottenham Hotspur FC", "tottenham"),
        ("Wolverhampton Wanderers FC", "wolves"),
        ("Brighton & Hove Albion FC", "brighton"),
        ("Nottingham Forest FC", "nottingham"),
    ],
)
def test_legacy_canonical_keys_are_frozen(source: str, expected: str) -> None:
    assert canonical_key(source) == expected


@pytest.mark.parametrize(
    ("league_key", "source", "target"),
    [
        ("bundesliga", "SC Paderborn 07", "Paderborn"),
        ("liga_portugal", "FC Famalicão", "Famalicao"),
        ("serie_a", "Udinese Calcio", "Udinese"),
    ],
)
def test_confirmed_registry_alias_uses_existing_team(
    tmp_path: Path, league_key: str, source: str, target: str
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, league_key, (target, "Other Club"))
        importer = FixtureHistoryImporter(store, private_root=root)
        state, fixture_id = _import_json(importer, league_key, "2026-27", source, "Other Club")
        assert state is MappingState.CONFIRMED
        assert fixture_id == deterministic_identifier(
            "fixture",
            f"{league_key}:2026-27:"
            f"{deterministic_identifier('team', f'{league_key}:{canonical_key(target)}')}:"
            f"{deterministic_identifier('team', f'{league_key}:other club')}",
        )
        assert len(importer.fixtures()) == 1


def test_registry_never_creates_a_missing_promoted_team(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Other Club",))
        importer = FixtureHistoryImporter(store, private_root=root)
        assert _import_json(importer, "bundesliga", "2026-27", "SC Paderborn 07", "Other Club") == (
            MappingState.UNKNOWN,
            None,
        )
        assert len(importer.fixtures()) == 0
        assert (
            len(store._connection_for_repository().execute("SELECT * FROM teams").fetchall()) == 1
        )


def test_promoted_team_resolves_only_after_its_canonical_identity_exists(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Elversberg", "Other Club"))
        importer = FixtureHistoryImporter(store, private_root=root)
        state, fixture_id = _import_json(
            importer, "bundesliga", "2026-27", "SV 07 Elversberg", "Other Club"
        )
        assert state is MappingState.CONFIRMED
        assert fixture_id is not None
        assert (
            len(store._connection_for_repository().execute("SELECT * FROM teams").fetchall()) == 2
        )


def test_registry_scope_and_whole_name_are_exact(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Paderborn", "Other Club"))
        _seed(store, "serie_a", ("Paderborn", "Other Club"))
        importer = FixtureHistoryImporter(store, private_root=root)
        for league, season, spelling in (
            ("bundesliga", "2025-26", "SC Paderborn 07"),
            ("serie_a", "2026-27", "SC Paderborn 07"),
            ("bundesliga", "2026-27", "SC Paderborn 07 Reserves"),
            ("bundesliga", "2026-27", "Paderbor"),
        ):
            assert _import_json(importer, league, season, spelling, "Other Club") == (
                MappingState.UNKNOWN,
                None,
            )


def test_canonical_evidence_disagreeing_with_registry_refuses_identity(tmp_path: Path) -> None:
    registry = _registry_with_update(
        "SC Paderborn 07", source_name="Dortmund", normalized_name="dortmund"
    )
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Paderborn", "Dortmund", "Other Club"))
        importer = FixtureHistoryImporter(store, private_root=root, team_alias_registry=registry)
        assert _import_json(importer, "bundesliga", "2026-27", "Dortmund", "Other Club") == (
            MappingState.UNKNOWN,
            None,
        )
        assert len(importer.fixtures()) == 0


def test_persisted_alias_conflict_with_registry_refuses_identity(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Paderborn", "Dortmund", "Other Club"))
        _add_alias(store, "bundesliga", "SC Paderborn 07", "Dortmund")
        importer = FixtureHistoryImporter(store, private_root=root)
        assert _import_json(importer, "bundesliga", "2026-27", "SC Paderborn 07", "Other Club") == (
            MappingState.UNKNOWN,
            None,
        )
        mapping_state = (
            store._connection_for_repository()
            .execute(
                """SELECT mapping_state FROM source_team_mappings
            WHERE source_team_name = 'SC Paderborn 07'"""
            )
            .fetchone()[0]
        )
        assert mapping_state == MappingState.AMBIGUOUS.value
        assert len(importer.fixtures()) == 0


def test_openfootball_alias_does_not_apply_to_another_lineage(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, "bundesliga", ("Paderborn", "Other Club"))
        importer = FixtureHistoryImporter(store, private_root=root)
        content = (
            b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
            b"D1,10/10/2026,15:00,SC Paderborn 07,Other Club,,,\n"
        )
        result = importer.import_dataset(
            FootballDataCSVParser().parse(
                content, league=league_by_key("bundesliga"), season="2026-27"
            ),
            content,
            SourceCaptureInput(
                source_url=football_data_url(league_by_key("bundesliga"), "2026-27"),
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
                observed_terms="Football-Data.co.uk restricted private local noncommercial use",
            ),
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        assert result.unresolved_rows == 1
        observation = importer.observations_for_capture(result.source_capture_id)[0]
        assert observation.fixture_id is None
        assert (
            default_registry().candidates(
                "bundesliga", "2026-27", "football-data", "SC Paderborn 07"
            )
            == ()
        )


def test_sibling_feeds_converge_and_keep_both_provenances(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("bundesliga")
    content = (
        b'{"matches":[{"date":"2026-10-09","time":"20:00",'
        b'"team1":"SC Paderborn 07","team2":"Dortmund","score":{}}]}'
    )
    text = (
        b"= German Bundesliga 2026/27\n\nMatchday 1\n\n"
        b"Fri Oct 9 2026\n\n20:00 SC Paderborn 07 v Dortmund\n"
    )
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, league.key, ("Paderborn", "Dortmund"))
        importer = FixtureHistoryImporter(store, private_root=root)
        result = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {
                    openfootball_url(league, "2026-27"): content,
                    openfootball_text_url(league, "2026-27"): text,
                },
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
            ),
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27", leagues=(league,), matchweek_friday="2026-10-09"
            )
        )
        assert len(importer.fixtures()) == 1
        assert len(result.assessment.identity_resolutions) == 1
        identity = result.assessment.identity_resolutions[0]
        assert len(identity.source_capture_ids) == 2
        assert len(identity.revision_ids) == 2
        assert len(identity.source_assertion_ids) >= 6


def test_deferred_current_fallback_seeds_completed_teams_before_schedule(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("premier_league")
    content = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-08-21",
                    "time": "20:00",
                    "team1": "Arsenal FC",
                    "team2": "Chelsea FC",
                    "score": {"ft": [2, 0]},
                },
                {
                    "date": "2026-10-09",
                    "time": "20:00",
                    "team1": "Chelsea FC",
                    "team2": "Arsenal FC",
                    "score": {},
                },
                {
                    "date": "2026-10-10",
                    "time": "20:00",
                    "team1": "Unknown Promoted",
                    "team2": "Arsenal FC",
                    "score": {},
                },
            ]
        }
    ).encode()
    text = (
        b"= English Premier League 2026/27\n\nMatchday 8\n\n"
        b"Fri Oct 9 2026\n\n20:00 Chelsea FC v Arsenal FC\n"
    )
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        importer = FixtureHistoryImporter(store, private_root=root)
        report = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {
                    openfootball_url(league, "2026-27"): content,
                    openfootball_text_url(league, "2026-27"): text,
                },
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
            ),
        ).acquire(
            IngestionPlan(
                current_season="2026-27", leagues=(league,), matchweek_friday="2026-10-09"
            )
        )
        assert report.fallback_imports == 1
        assert report.imports[0].fixtures_seen == 3
        assert len(importer.observations_for_capture(report.imports[0].source_capture_id)) == 3
        assert (
            store._connection_for_repository().execute("SELECT COUNT(*) FROM teams").fetchone()[0]
            == 2
        )
        assert report.scheduled_fixtures is not None
        resolved = [
            item
            for item in report.scheduled_fixtures.assessment.identity_resolutions
            if item.canonical_fixture_id is not None
        ]
        assert len(resolved) == 1
        assert len(resolved[0].source_capture_ids) == 2


def test_reacquiring_identical_schedule_keeps_original_revision_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("premier_league")
    url = openfootball_url(league, "2026-27")
    content = (
        b'{"matches":[{"date":"2026-10-09","time":"20:00",'
        b'"team1":"Arsenal FC","team2":"Chelsea FC","score":{}}]}'
    )
    fetcher = StaticSourceFetcher({url: content}, retrieved_at_utc="2026-09-29T10:00:00+00:00")
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, league.key, ("Arsenal FC", "Chelsea FC"))
        importer = FixtureHistoryImporter(store, private_root=root)
        acquirer = FixtureHistoryAcquirer(importer, fetcher)
        plan = IngestionPlan(
            current_season="2026-27", leagues=(league,), matchweek_friday="2026-10-09"
        )
        first = acquirer.acquire_scheduled_fixtures(plan)
        first_attempt = next(
            item
            for item in first.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        first_revision_id = first.assessment.fixture_revisions[0].revision_id

        fetcher.retrieved_at_utc = "2026-09-29T10:05:00+00:00"
        second = acquirer.acquire_scheduled_fixtures(plan)
        second_attempt = next(
            item
            for item in second.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        revision = second.assessment.fixture_revisions[0]
        assert second_attempt.capture_id != first_attempt.capture_id
        assert revision.revision_id == first_revision_id
        assert second_attempt.capture_id in revision.source_capture_ids
        assert first_attempt.capture_id not in revision.source_capture_ids


def test_registry_digest_and_duplicate_entries_fail_closed() -> None:
    registry = default_registry()
    assert registry.version == "matchvet-team-alias-registry-v1"
    assert registry.digest == default_registry().digest
    registry_path = Path(__file__).parents[1] / "src/matchvet/team_alias_registry_v1.json"
    raw = json.loads(registry_path.read_text())
    assert raw["digest"].startswith("sha256:")

    tampered = json.loads(registry_path.read_text())
    tampered["entries"][0]["canonical_name"] = "Changed without registry digest"
    with pytest.raises(ValueError, match="digest"):
        TeamAliasRegistry.from_json(json.dumps(tampered).encode())

    raw["entries"].append(raw["entries"][0].copy())
    canonical_payload = {"version": raw["version"], "entries": raw["entries"]}
    raw["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                canonical_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()
    )
    with pytest.raises(ValueError, match="Duplicate"):
        TeamAliasRegistry.from_json(json.dumps(raw).encode())
    with pytest.raises(ValueError, match="Malformed"):
        TeamAliasRegistry.from_json(b"not JSON")


def test_historical_openfootball_lommel_collision_stays_unresolved(tmp_path: Path) -> None:
    from dataclasses import replace

    root = tmp_path / "private"
    root.mkdir()
    league = league_by_key("belgian_pro_league")
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        _seed(store, league.key, ("Lommel United", "KFC Lommel SK"))
        league_id = deterministic_identifier("league", league.key)
        teams = {
            str(row[1]): str(row[0])
            for row in store._connection_for_repository()
            .execute("SELECT team_id, canonical_name FROM teams WHERE league_id = ?", (league_id,))
            .fetchall()
        }
        with store.transaction() as tx:
            for team_name in ("Lommel United", "KFC Lommel SK"):
                team_id = teams[team_name]
                alias_id = deterministic_identifier(
                    "team_alias", f"{league.key}:{team_id}:{canonical_key('Lommel')}"
                )
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
                        "Lommel",
                        canonical_key("Lommel"),
                        "openfootball-clubs-historical-candidate",
                        "2026-09-29T12:00:00+00:00",
                    ),
                )
        importer = FixtureHistoryImporter(store, private_root=root)
        parsed = OpenFootballJSONParser().parse(
            b'{"matches":[{"date":"2026-10-10","time":"15:00",'
            b'"team1":"Lommel","team2":"KFC Lommel SK","score":{}}]}',
            league=league_by_key("bundesliga"),
            season="2026-27",
        )
        result = importer.import_dataset(
            replace(parsed, league=league),
            b'{"matches":[{"date":"2026-10-10","time":"15:00",'
            b'"team1":"Lommel","team2":"KFC Lommel SK","score":{}}]}',
            SourceCaptureInput(
                source_url="https://example.test/historical-lommel.json",
                retrieved_at_utc="2026-09-29T12:00:00+00:00",
                observed_terms="OpenFootball CC0",
            ),
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        assert result.unresolved_rows == 1
        assert (
            default_registry().candidates(league.key, "2026-27", "openfootball-schedule", "Lommel")
            == ()
        )
        assert importer.fixtures() == ()


def test_offline_live_source_name_corpus_resolves_85_of_86(tmp_path: Path) -> None:
    corpus = json.loads((Path(__file__).parent / "fixtures/lf03_live_names.json").read_text())
    root = tmp_path / "private"
    root.mkdir()
    unresolved: list[tuple[str, str]] = []
    resolved = 0
    with open_store(root / "matchvet.sqlite3", private_root=root) as store:
        for league_record in corpus["leagues"]:
            _seed(
                store,
                league_record["league_key"],
                tuple(team["canonical_name"] for team in league_record["existing_canonical_teams"]),
            )
        importer = FixtureHistoryImporter(store, private_root=root)
        for league_record in corpus["leagues"]:
            league_key = league_record["league_key"]
            league = league_by_key(league_key)
            first, second = league_record["existing_canonical_teams"][:2]
            names = league_record["source_spellings"]
            registry = default_registry()

            content = json.dumps(
                {
                    "matches": [
                        {
                            "date": "2026-10-09",
                            "time": "20:00",
                            "team1": name,
                            "team2": _different_opponent(name, league_key, first, second, registry),
                            "score": {},
                        }
                        for name in names
                    ]
                },
                ensure_ascii=False,
            ).encode()
            dataset = OpenFootballJSONParser().parse(content, league=league, season="2026-27")
            names_by_key = {row.source_row_key: row.home_team for row in dataset.rows}
            imported = importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url=openfootball_url(league, "2026-27"),
                    retrieved_at_utc="2026-09-29T12:00:00+00:00",
                    observed_terms="OpenFootball CC0",
                ),
                identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
            )
            observations = importer.observations_for_capture(imported.source_capture_id)
            for observation in observations:
                name = names_by_key[observation.source_row_key]
                if observation.fixture_id is None:
                    unresolved.append((league_key, name))
                else:
                    resolved += 1
    assert resolved == 85
    assert unresolved == [("liga_portugal", "Gil Vicente FC           [postponed]")]

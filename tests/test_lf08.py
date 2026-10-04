"""LF08 fresh current-season Premier League coverage through public acquisition."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from matchvet.ingestion import (
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    FootballDataCSVParser,
    IngestionPlan,
    MappingState,
    OpenFootballJSONParser,
    SourceCaptureInput,
    SourceKind,
    StaticSourceFetcher,
    TeamIdentityPolicy,
    canonical_key,
    football_data_url,
    league_by_key,
    openfootball_text_url,
    openfootball_url,
)
from matchvet.store import open_store
from matchvet.team_alias_registry import TeamAliasRegistry, default_registry

_ADDED_NAMES = {"Hull City AFC", "Ipswich Town FC", "Newcastle United FC", "Nottingham Forest FC"}
_V1_DIGEST = "sha256:1bdae3b0888acc35e03f691739c16a7930bcf3ff42d7c3d9619842d16a90b86a"
_V2_DIGEST = "sha256:7ceb69ae874d8e83f8358960d347b7bedf3a5e229c29b9f50ef7d5e63d0fbccd"
_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("snapshot,expected_unresolved", [("v1", 8), ("v2", 0)])
def test_fresh_current_season_four_fixtures_converge(
    tmp_path: Path, snapshot: str, expected_unresolved: int
) -> None:
    league = league_by_key("premier_league")
    identities = json.loads((_FIXTURES / "lf08_premier_league_identities.json").read_bytes())
    names = [item["canonical_name"] for item in identities]
    history = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        + "\n".join(
            f"E0,21/08/2026,20:00,{home},{away},1,0,H"
            for home, away in zip(names[::2], names[1::2], strict=True)
        )
        + "\n"
    ).encode()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        registry = TeamAliasRegistry.from_json(
            files("matchvet").joinpath(f"team_alias_registry_{snapshot}.json").read_bytes()
        )
        importer = FixtureHistoryImporter(
            store, private_root=tmp_path, team_alias_registry=registry
        )
        importer.import_dataset(
            FootballDataCSVParser().parse(history, league=league, season="2026-27"),
            history,
            SourceCaptureInput(
                source_url=football_data_url(league, "2026-27"),
                retrieved_at_utc="2026-09-30T12:00:00+00:00",
                observed_terms="Synthetic offline current-season test data",
            ),
        )
        before = importer.fixtures()
        connection = store._connection_for_repository()
        teams_before = tuple(connection.execute("SELECT * FROM teams ORDER BY team_id"))
        aliases_before = tuple(connection.execute("SELECT * FROM team_aliases ORDER BY alias_id"))
        assert len(teams_before) == 20
        assert {fixture.season for fixture in before} == {"2026-27"}
        assert store.status.schema_version == 14
        assert store.status.applied_migrations == tuple(range(1, 15))
        for item in identities:
            assert canonical_key(item["source_name"]) == item["normalized_name"]
            for kind in (SourceKind.OPENFOOTBALL, SourceKind.OPENFOOTBALL_TEXT):
                resolution = importer.resolve_existing_team(
                    league, "2026-27", item["source_name"], source_kind=kind
                )
                needs_alias = item["source_name"] in _ADDED_NAMES
                if snapshot == "v1" and needs_alias:
                    assert resolution.state is MappingState.UNKNOWN
                else:
                    assert resolution.canonical_team_id == item["team_id"]
        assert len(identities) == 20
        report = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(
                {
                    openfootball_url(league, "2026-27"): (
                        _FIXTURES / "lf08_openfootball.json"
                    ).read_bytes(),
                    openfootball_text_url(league, "2026-27"): (
                        _FIXTURES / "lf08_openfootball.txt"
                    ).read_bytes(),
                },
                retrieved_at_utc="2026-09-30T12:05:00+00:00",
            ),
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27", leagues=(league,), matchweek_friday="2026-10-09"
            )
        )
        resolutions = report.assessment.identity_resolutions
        unresolved = [item for item in resolutions if item.canonical_fixture_id is None]
        assert len(unresolved) == expected_unresolved
        assert tuple(connection.execute("SELECT * FROM teams ORDER BY team_id")) == teams_before
        assert (
            tuple(connection.execute("SELECT * FROM team_aliases ORDER BY alias_id"))
            == aliases_before
        )
        assert all(fixture in importer.fixtures() for fixture in before)
        assert len(report.imports) == 2
        observations = [
            importer.observations_for_capture(item.source_capture_id) for item in report.imports
        ]
        assert [len(items) for items in observations] == [4, 4]
        assert {item.source_key for item in importer.source_captures()} == {
            "football-data.co.uk",
            "openfootball",
            "openfootball-footballtxt",
        }
        if expected_unresolved:
            assert {item.reason_code for item in unresolved} == {"TEAM_MAPPING_UNRESOLVED"}
            return
        assert len(importer.fixtures()) == len(before) + 4
        assert {item.fixture_id for item in observations[0]} == {
            item.fixture_id for item in observations[1]
        }
        assert len(resolutions) == 4
        assert len({item.canonical_fixture_id for item in resolutions}) == 4
        assert all(len(item.source_capture_ids) == 2 for item in resolutions)


def test_registry_snapshots_keep_exact_bytes_versions_and_entries() -> None:
    v1_bytes = files("matchvet").joinpath("team_alias_registry_v1.json").read_bytes()
    v2_bytes = files("matchvet").joinpath("team_alias_registry_v2.json").read_bytes()
    assert hashlib.sha256(v1_bytes).hexdigest() == (
        "252e7eb14f628573b2122844b41f64f8f72ffeec0ef9e2f0026e5698132dac98"
    )
    assert hashlib.sha256(v2_bytes).hexdigest() == (
        "df3d635d4f9e1d6b9d41ab1305f3d77c99b39043661cb35117b4f62b2747a635"
    )
    v1 = TeamAliasRegistry.from_json(v1_bytes)
    v2 = TeamAliasRegistry.from_json(v2_bytes)
    assert (v1.version, v1.digest) == ("matchvet-team-alias-registry-v1", _V1_DIGEST)
    assert (v2.version, v2.digest) == ("matchvet-team-alias-registry-v2", _V2_DIGEST)
    assert default_registry() == v2
    assert set(v1.entries).issubset(v2.entries)
    assert {item.source_name for item in set(v2.entries) - set(v1.entries)} == _ADDED_NAMES
    payload = json.loads(v2_bytes)
    assert v2_bytes == (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode()
    assert TeamAliasRegistry.from_json(json.dumps(payload, sort_keys=True).encode()) == v2


def _signed_payload(payload: dict[str, Any]) -> bytes:
    payload["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {"version": payload["version"], "entries": payload["entries"]},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "version",
        "missing_field",
        "wrong_id",
        "normalization",
        "provenance",
        "duplicate",
        "conflict",
        "unsorted",
        "empty",
        "invalid_json",
    ],
)
def test_malformed_v2_fails_closed(mutation: str) -> None:
    payload = json.loads(files("matchvet").joinpath("team_alias_registry_v2.json").read_bytes())
    entry = payload["entries"][0]
    if mutation == "digest":
        payload["digest"] = "sha256:" + "0" * 64
    elif mutation == "version":
        payload["version"] = "matchvet-team-alias-registry-v3"
    elif mutation == "missing_field":
        del entry["confirmation"]
    elif mutation == "wrong_id":
        entry["team_id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "normalization":
        entry["normalized_name"] = "wrong"
    elif mutation == "provenance":
        entry["provenance_type"] = "FUZZY"
    elif mutation in ("duplicate", "conflict"):
        duplicate = dict(entry)
        if mutation == "conflict":
            target = payload["entries"][1]
            duplicate.update(team_id=target["team_id"], canonical_name=target["canonical_name"])
        payload["entries"].insert(1, duplicate)
    elif mutation == "unsorted":
        payload["entries"].reverse()
    elif mutation == "empty":
        entry["source_name"] = ""
    content = json.dumps(payload).encode() if mutation == "digest" else _signed_payload(payload)
    if mutation == "invalid_json":
        content = b"{"
    with pytest.raises(ValueError):
        TeamAliasRegistry.from_json(content)


@pytest.mark.parametrize("source_name", sorted(_ADDED_NAMES))
def test_new_aliases_do_not_escape_scope(tmp_path: Path, source_name: str) -> None:
    league = league_by_key("premier_league")
    history = (
        b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"E0,21/08/2026,Hull,Ipswich,1,0,H\n"
        b"E0,22/08/2026,Newcastle,Nott'm Forest,1,0,H\n"
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        importer.import_dataset(
            FootballDataCSVParser().parse(history, league=league, season="2026-27"),
            history,
            SourceCaptureInput(
                source_url=football_data_url(league, "2026-27"),
                retrieved_at_utc="2026-09-30T12:00:00+00:00",
                observed_terms="Synthetic offline test data",
            ),
        )
        for key, season, kind in (
            ("premier_league", "2025-26", SourceKind.OPENFOOTBALL),
            ("serie_a", "2026-27", SourceKind.OPENFOOTBALL),
            ("premier_league", "2026-27", SourceKind.FOOTBALL_DATA),
            ("premier_league", "2026-27", SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION),
        ):
            assert (
                importer.resolve_existing_team(
                    league_by_key(key), season, source_name, source_kind=kind
                ).state
                is MappingState.UNKNOWN
            )
        for kind in (SourceKind.OPENFOOTBALL, SourceKind.OPENFOOTBALL_TEXT):
            assert (
                importer.resolve_existing_team(
                    league, "2026-27", source_name, source_kind=kind
                ).state
                is MappingState.CONFIRMED
            )


def test_v1_capture_replay_preserves_mapping_provenance_under_v2(tmp_path: Path) -> None:
    league = league_by_key("serie_a")
    content = (
        b'{"matches":[{"date":"2026-08-21","team1":"ACF Fiorentina","team2":"AS Roma","score":{}}]}'
    )
    dataset = OpenFootballJSONParser().parse(content, league=league, season="2026-27")
    capture = SourceCaptureInput(
        source_url=openfootball_url(league, "2026-27"),
        retrieved_at_utc="2026-09-30T12:00:00+00:00",
        observed_terms="Synthetic offline test data",
    )
    old = TeamAliasRegistry.from_json(
        files("matchvet").joinpath("team_alias_registry_v1.json").read_bytes()
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path, team_alias_registry=old)
        initial = importer.import_dataset(
            dataset, content, capture, identity_policy=TeamIdentityPolicy.REGISTER_UNKNOWN
        )
        assert initial.unresolved_rows == 0
        fixtures = importer.fixtures()
        connection = store._connection_for_repository()
        mappings = tuple(
            connection.execute("SELECT * FROM source_team_mappings ORDER BY mapping_id")
        )
        assert {
            row[0]
            for row in connection.execute("SELECT mapping_rule_version FROM source_team_mappings")
        } == {f"{old.version}:{old.digest}"}
        current = FixtureHistoryImporter(store, private_root=tmp_path)
        replay = current.import_dataset(
            dataset, content, capture, identity_policy=TeamIdentityPolicy.KNOWN_ONLY
        )
        assert replay.from_existing_capture
        assert current.fixtures() == fixtures
        assert (
            tuple(connection.execute("SELECT * FROM source_team_mappings ORDER BY mapping_id"))
            == mappings
        )
        for name in ("ACF Fiorentina", "AS Roma"):
            assert (
                current.resolve_existing_team(
                    league, "2026-27", name, source_kind=SourceKind.OPENFOOTBALL
                ).state
                is MappingState.CONFIRMED
            )

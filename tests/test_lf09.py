"""LF09 official Pro League identity policy at the importer and LF05 boundaries."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from datetime import date
from importlib.resources import files
from pathlib import Path
from subprocess import run

import pytest
from test_operator_fixture_observation import _seed_league_teams, _valid_input

from matchvet.ingestion import (
    FixtureHistoryImporter,
    MappingState,
    ParsedDataset,
    ParsedRow,
    SourceCaptureInput,
    SourceKind,
    TeamIdentityPolicy,
    canonical_key,
    deterministic_identifier,
    league_by_key,
)
from matchvet.operator_fixture_observation import OperatorFixtureObservationRepository
from matchvet.pro_league_team_alias_registry import (
    ProLeagueTeamAliasRegistry,
    default_pro_league_registry,
)
from matchvet.store import CanonicalIdentifier, open_store


def test_official_source_resolves_reviewed_beveren_name(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Beveren",))
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        resolution = importer.resolve_existing_team(
            league_by_key("belgian_pro_league"), "2026-27", "SK Beveren"
        )
        assert resolution.state is MappingState.CONFIRMED
        assert resolution.canonical_name == "Beveren"


_NAMES = (
    ("SK Beveren", "Beveren"),
    ("Lommel SK", "Lommel SK"),
    ("Cercle Brugge", "Cercle Brugge"),
    ("RSC Anderlecht", "Anderlecht"),
    ("RAAL La Louvière", "RAAL La Louviere"),
    ("Club Brugge", "Club Brugge"),
    ("KRC Genk", "Genk"),
    ("KV Kortrijk", "Kortrijk"),
    ("SV Zulte Waregem", "Waregem"),
    ("KAA Gent", "Gent"),
    ("Standard de Liège", "Standard"),
    ("Sporting Charleroi", "Charleroi"),
    ("Royale Union Saint-Gilloise", "St. Gilloise"),
    ("OH Leuven", "Oud-Heverlee Leuven"),
    ("KVC Westerlo", "Westerlo"),
    ("Royal Antwerp FC", "Antwerp"),
    ("KV Mechelen", "Mechelen"),
    ("STVV", "St Truiden"),
)
_FIXTURES = tuple(zip(_NAMES[::2], _NAMES[1::2], strict=True))
_OFFICIAL_DIGEST = "sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213"


def _all_teams(store: object) -> None:
    _seed_league_teams(store, tuple(target for _, target in _NAMES))


def _resigned(payload: dict[str, object]) -> bytes:
    core = {"version": payload["version"], "entries": payload["entries"]}
    payload["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return json.dumps(payload).encode()


def test_official_registry_has_frozen_scope_and_reviewed_targets() -> None:
    registry = default_pro_league_registry()
    assert registry.version == "matchvet-pro-league-team-alias-registry-v1"
    assert registry.digest == _OFFICIAL_DIGEST
    assert len(registry.entries) == 15
    assert {entry.source_name: entry.canonical_name for entry in registry.entries} == {
        source: target for source, target in _NAMES if source != target
    }
    assert all(entry.confirmation.startswith("LF09 reviewed") for entry in registry.entries)
    assert all(
        entry.source_locator == "https://www.proleague.be/jpl-kalender!"
        for entry in registry.entries
    )


def test_eighteen_official_names_resolve_in_fresh_store(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _all_teams(store)
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        league = league_by_key("belgian_pro_league")
        results = [
            importer.resolve_existing_team(league, "2026-27", source) for source, _ in _NAMES
        ]
        assert [item.state for item in results] == [MappingState.CONFIRMED] * 18
        assert [item.canonical_name for item in results] == [target for _, target in _NAMES]
        assert [item.canonical_team_id for item in results] == [
            deterministic_identifier("team", f"belgian_pro_league:{canonical_key(target)}")
            for _, target in _NAMES
        ]
        assert store.status.schema_version == 14
        assert store.status.applied_migrations == tuple(range(1, 15))


def test_nine_lf05_pairings_are_identity_ready_without_observations(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _all_teams(store)
        repository = OperatorFixtureObservationRepository(store, private_root=tmp_path)
        league = league_by_key("belgian_pro_league")
        ready = []
        for (home, _), (away, _) in _FIXTURES:
            home_resolution = repository._resolve_team(league, "2026-27", home, "Home")
            away_resolution = repository._resolve_team(league, "2026-27", away, "Away")
            ready.append(
                home_resolution.state is MappingState.CONFIRMED
                and away_resolution.state is MappingState.CONFIRMED
                and home_resolution.canonical_team_id != away_resolution.canonical_team_id
            )
        assert ready == [True] * 9
        assert (
            store._connection_for_repository()
            .execute("SELECT count(*) FROM source_captures")
            .fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "kind", [SourceKind.FOOTBALL_DATA, SourceKind.OPENFOOTBALL, SourceKind.OPENFOOTBALL_TEXT]
)
def test_official_alias_is_unavailable_to_other_sources(tmp_path: Path, kind: SourceKind) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Beveren",))
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        assert (
            importer.resolve_existing_team(
                league_by_key("belgian_pro_league"), "2026-27", "SK Beveren", source_kind=kind
            ).state
            is MappingState.UNKNOWN
        )


def test_official_alias_requires_exact_name_league_and_season(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Beveren",))
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        league = league_by_key("belgian_pro_league")
        assert (
            importer.resolve_existing_team(league, "2025-26", "SK Beveren").state
            is MappingState.UNKNOWN
        )
        assert (
            importer.resolve_existing_team(league, "2026-27", "sk beveren").state
            is MappingState.UNKNOWN
        )
        assert (
            importer.resolve_existing_team(
                league_by_key("premier_league"), "2026-27", "SK Beveren"
            ).state
            is MappingState.UNKNOWN
        )


def test_direct_same_identity_confirms_and_competing_identity_is_ambiguous(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Beveren",))
        league = league_by_key("belgian_pro_league")
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        same = importer.resolve_existing_team(league, "2026-27", "SK Beveren")
        assert same.state is MappingState.CONFIRMED
        # A persisted whole-name alias to the reviewed target adds the same ID.
        with store.transaction() as tx:
            alias_id = deterministic_identifier("test_alias", "SK Beveren:Beveren")
            tx.add_identifier_if_missing(CanonicalIdentifier("team_alias", alias_id))
            tx.execute(
                """INSERT INTO team_aliases (alias_id, league_id, team_id, source_id,
                alias_name, normalized_alias, mapping_rule_version, created_at_utc)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    alias_id,
                    deterministic_identifier("league", league.key),
                    same.canonical_team_id,
                    "SK Beveren",
                    canonical_key("SK Beveren"),
                    "test-reviewed-v1",
                    "2026-09-01T00:00:00+00:00",
                ),
            )
        assert (
            importer.resolve_existing_team(league, "2026-27", "SK Beveren").state
            is MappingState.CONFIRMED
        )
    other = tmp_path / "competing"
    other.mkdir()
    with open_store(other / "matchvet.sqlite3", private_root=other) as store:
        _seed_league_teams(store, ("Beveren", "SK Beveren"))
        importer = FixtureHistoryImporter(store, private_root=other)
        assert (
            importer.resolve_existing_team(league, "2026-27", "SK Beveren").state
            is MappingState.AMBIGUOUS
        )


def test_missing_registry_target_remains_unknown(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        assert (
            importer.resolve_existing_team(
                league_by_key("belgian_pro_league"), "2026-27", "SK Beveren"
            ).state
            is MappingState.UNKNOWN
        )


def test_official_source_cannot_register_missing_reviewed_target(tmp_path: Path) -> None:
    league = league_by_key("belgian_pro_league")
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Lommel SK",))
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        result = importer.import_dataset(
            ParsedDataset(
                SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION,
                league,
                "2026-27",
                (
                    ParsedRow(
                        source_row_key="missing-reviewed-target",
                        home_team="SK Beveren",
                        away_team="Lommel SK",
                        kickoff_utc=None,
                        kickoff_local_date=date(2026, 10, 9),
                        kickoff_local_text="2026-10-09",
                        kickoff_precision="DATE",
                        fields={},
                        raw_fields={},
                        explicit_fixture_status="SCHEDULED",
                    ),
                ),
                "test-official",
            ),
            b"synthetic official test capture",
            SourceCaptureInput(
                source_url="https://www.proleague.be/jpl-kalender!",
                retrieved_at_utc="2026-09-30T12:00:00+00:00",
                observed_terms="RESEARCH_ONLY:MANUAL_CITATION",
            ),
            identity_policy=TeamIdentityPolicy.REGISTER_UNKNOWN,
        )
        assert result.unresolved_rows == 1
        assert (
            store._connection_for_repository().execute("SELECT count(*) FROM teams").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "mutation",
    ["digest", "scope", "season", "lineage", "target", "duplicate", "normalization", "provenance"],
)
def test_corrupt_official_registry_fails_closed(mutation: str) -> None:
    payload = json.loads(
        files("matchvet").joinpath("pro_league_team_alias_registry_v1.json").read_bytes()
    )
    entry = payload["entries"][0]
    if mutation == "digest":
        entry["canonical_name"] = "Corrupt"
        content = json.dumps(payload).encode()
    else:
        if mutation == "scope":
            entry["league_key"] = "premier_league"
        elif mutation == "season":
            entry["season"] = "2025-26"
        elif mutation == "lineage":
            entry["source_lineage"] = "openfootball-schedule"
        elif mutation == "target":
            entry["team_id"] = "00000000-0000-0000-0000-000000000000"
        elif mutation == "normalization":
            entry["normalized_name"] = "wrong"
        elif mutation == "provenance":
            entry["source_locator"] = "https://other.example/fixtures"
        elif mutation == "duplicate":
            payload["entries"].insert(
                1, dict(entry, team_id="00000000-0000-0000-0000-000000000000")
            )
        content = _resigned(payload)
    with pytest.raises(ValueError):
        ProLeagueTeamAliasRegistry.from_json(content)


def test_injected_official_registry_is_revalidated(tmp_path: Path) -> None:
    registry = default_pro_league_registry()
    invalid = replace(
        registry, entries=(replace(registry.entries[0], team_id="wrong"), *registry.entries[1:])
    )
    with (
        open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store,
        pytest.raises(ValueError),
    ):
        FixtureHistoryImporter(store, private_root=tmp_path, pro_league_team_alias_registry=invalid)


def test_resigned_official_registry_cannot_retarget_reviewed_name() -> None:
    payload = json.loads(
        files("matchvet").joinpath("pro_league_team_alias_registry_v1.json").read_bytes()
    )
    entry = next(item for item in payload["entries"] if item["source_name"] == "SK Beveren")
    entry["canonical_name"] = "Lommel SK"
    entry["team_id"] = deterministic_identifier("team", "belgian_pro_league:lommel sk")
    with pytest.raises(ValueError):
        ProLeagueTeamAliasRegistry.from_json(_resigned(payload))


def test_official_observation_persists_official_mapping_provenance(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _all_teams(store)
        repository = OperatorFixtureObservationRepository(store, private_root=tmp_path)
        result = repository.record(_valid_input(home="SK Beveren", away="Lommel SK"))
        assert result.import_result.unresolved_rows == 0
        mappings = dict(
            store._connection_for_repository().execute(
                "SELECT source_team_name, mapping_rule_version FROM source_team_mappings"
            )
        )
        assert (
            mappings["SK Beveren"] == f"{default_pro_league_registry().version}:{_OFFICIAL_DIGEST}"
        )
        assert mappings["Lommel SK"] == mappings["SK Beveren"]
        assert (
            store._connection_for_repository()
            .execute("SELECT count(*) FROM team_aliases")
            .fetchone()[0]
            == 0
        )


def test_official_policy_provenance_is_unavailable_to_other_seasons(tmp_path: Path) -> None:
    league = league_by_key("belgian_pro_league")
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        _seed_league_teams(store, ("Lommel SK", "Cercle Brugge"))
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        result = importer.import_dataset(
            ParsedDataset(
                SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION,
                league,
                "2025-26",
                (
                    ParsedRow(
                        source_row_key="prior-season-direct-names",
                        home_team="Lommel SK",
                        away_team="Cercle Brugge",
                        kickoff_utc=None,
                        kickoff_local_date=date(2025, 10, 9),
                        kickoff_local_text="2025-10-09",
                        kickoff_precision="DATE",
                        fields={},
                        raw_fields={},
                        explicit_fixture_status="SCHEDULED",
                    ),
                ),
                "test-out-of-scope-official",
            ),
            b"synthetic prior-season official capture",
            SourceCaptureInput(
                source_url="https://www.proleague.be/jpl-kalender!",
                retrieved_at_utc="2025-09-30T12:00:00+00:00",
                observed_terms="RESEARCH_ONLY:MANUAL_CITATION",
            ),
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        assert result.unresolved_rows == 0
        versions = {
            row[0]
            for row in store._connection_for_repository().execute(
                "SELECT mapping_rule_version FROM source_team_mappings"
            )
        }
        assert f"{default_pro_league_registry().version}:{_OFFICIAL_DIGEST}" not in versions


def test_wheel_contains_exact_official_registry_bytes(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "src/matchvet/pro_league_team_alias_registry_v1.json"
    result = run(
        ["uv", "build", "--wheel", "--offline", "--out-dir", str(tmp_path), "."],
        cwd=source.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert wheel.read("matchvet/pro_league_team_alias_registry_v1.json") == source.read_bytes()

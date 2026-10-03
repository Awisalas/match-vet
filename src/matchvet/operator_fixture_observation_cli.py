"""Small explicit-store workflow for LF05 official fixture observations."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from matchvet.ingestion import FixtureHistoryImporter, league_by_key
from matchvet.operator_fixture_observation import (
    OfficialFixtureObservationInput,
    OperatorFixtureObservationRepository,
)
from matchvet.store import Store, StoreMode, open_store


def add_fixture_observation_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    observe = commands.add_parser("observe", help="record Research-Only official fixture facts")
    observe_commands = observe.add_subparsers(dest="observe_command", required=True)
    official = observe_commands.add_parser(
        "official", help="use an approved official scheduling citation"
    )
    official_commands = official.add_subparsers(dest="official_command", required=True)
    record = official_commands.add_parser("record", help="record one cited fixture observation")
    record.add_argument("--store", type=Path, required=True, help="explicit private database path")
    record.add_argument("--league", required=True, help="configured league key")
    record.add_argument("--season", required=True, help="season in YYYY-YY form")
    record.add_argument("--friday", required=True, help="exact Matchweek Friday YYYY-MM-DD")
    record.add_argument("--home", required=True, help="official source spelling of the home team")
    record.add_argument("--away", required=True, help="official source spelling of the away team")
    record.add_argument(
        "--kickoff",
        required=True,
        help="YYYY-MM-DD or offset-aware ISO-8601 instant",
    )
    record.add_argument(
        "--status",
        required=True,
        choices=("SCHEDULED", "POSTPONED", "CANCELLED"),
    )
    record.add_argument("--official-url", required=True, help="exact approved publication URL")
    record.add_argument("--publication-id", required=True, help="approved publication identity")
    record.add_argument(
        "--publication-type",
        required=True,
        help="publication type approved by the versioned observation policy",
    )
    record.add_argument("--title", required=True, help="publication title or identifier")
    record.add_argument(
        "--publication-date",
        help="publication date YYYY-MM-DD when shown by the official source",
    )
    record.add_argument("--operator-id", required=True, help="explicit stable operator identity")
    record.add_argument("--json", action="store_true", dest="as_json", help="print compact JSON")

    listing = official_commands.add_parser("list", help="list observations for one exact scope")
    listing.add_argument("--store", type=Path, required=True, help="explicit private database path")
    listing.add_argument("--league", required=True, help="configured league key")
    listing.add_argument("--season", required=True, help="season in YYYY-YY form")
    listing.add_argument("--friday", required=True, help="exact Matchweek Friday YYYY-MM-DD")
    listing.add_argument("--json", action="store_true", dest="as_json", help="print compact JSON")


def handle_fixture_observation(arguments: argparse.Namespace) -> int:
    try:
        if arguments.official_command == "record":
            return _record(arguments)
        if arguments.official_command == "list":
            return _list(arguments)
        raise ValueError("Choose fixtures observe official record or list.")
    except (OSError, RuntimeError, sqlite3.DatabaseError, TypeError, ValueError) as error:
        return _emit(
            arguments,
            {"mode": "RESEARCH_ONLY", "status": "REFUSED", "reason": str(error)},
            exit_code=1,
        )


def _record(arguments: argparse.Namespace) -> int:
    observation_input = OfficialFixtureObservationInput(
        league_key=arguments.league,
        season=arguments.season,
        friday=arguments.friday,
        home=arguments.home,
        away=arguments.away,
        kickoff=arguments.kickoff,
        status=arguments.status,
        official_url=arguments.official_url,
        publication_id=arguments.publication_id,
        publication_type=arguments.publication_type,
        title=arguments.title,
        publication_date=arguments.publication_date,
        operator_id=arguments.operator_id,
    )
    with _open(arguments.store) as store:
        repository = OperatorFixtureObservationRepository(
            store, private_root=arguments.store.parent
        )
        persisted = repository.record(observation_input)
        fixture_names = _fixture_names(store, arguments.store.parent, persisted.fixture_id)
        return _emit(
            arguments,
            {
                "mode": "RESEARCH_ONLY",
                "scope_id": persisted.observation.scope_id,
                "resolved_fixture": f"{fixture_names[0]} vs {fixture_names[1]}",
                "kickoff_precision": persisted.observation.kickoff_precision,
                "kickoff_utc": persisted.observation.kickoff_utc,
                "kickoff_source_date": persisted.observation.source_local_date,
                "status": persisted.observation.fixture_status,
                "observation_digest": persisted.observation.digest,
                "artifact_digest": persisted.artifact_digest,
            },
        )


def _list(arguments: argparse.Namespace) -> int:
    league = league_by_key(arguments.league)
    from matchvet.fixture_coverage import fixture_scopes_for_matchweek

    scopes = fixture_scopes_for_matchweek(arguments.friday, season=arguments.season)
    scope = next(item for item in scopes if item.league_key == league.key)
    with _open(arguments.store) as store:
        records = OperatorFixtureObservationRepository(
            store, private_root=arguments.store.parent
        ).list_for_scope(scope.scope_id)
        names = {
            item.fixture_id: (item.home_team_name, item.away_team_name)
            for item in FixtureHistoryImporter(
                store, private_root=arguments.store.parent
            ).fixtures()
        }
        entries = [
            {
                "resolved_fixture": f"{names[item.fixture_id][0]} vs {names[item.fixture_id][1]}",
                "kickoff_precision": item.observation.kickoff_precision,
                "kickoff_utc": item.observation.kickoff_utc,
                "kickoff_source_date": item.observation.source_local_date,
                "status": item.observation.fixture_status,
                "observation_digest": item.observation.digest,
                "artifact_digest": item.artifact_digest,
            }
            for item in records
        ]
        return _emit(
            arguments,
            {
                "mode": "RESEARCH_ONLY",
                "scope_id": scope.scope_id,
                "observations": entries,
            },
        )


def _fixture_names(store: Store, private_root: Path, fixture_id: str) -> tuple[str, str]:
    fixture = next(
        (
            item
            for item in FixtureHistoryImporter(store, private_root=private_root).fixtures()
            if item.fixture_id == fixture_id
        ),
        None,
    )
    if fixture is None:
        raise ValueError("Recorded fixture could not be resolved from ordinary provenance.")
    return fixture.home_team_name, fixture.away_team_name


def _open(database_path: Path) -> Store:
    if not database_path.is_absolute():
        database_path = database_path.resolve()
    store = open_store(database_path, private_root=database_path.parent)
    if store.status.mode is not StoreMode.READ_WRITE:
        issue = store.status.issues[0]
        store.close()
        raise RuntimeError(f"{issue.code}: {issue.message}")
    return store


def _emit(
    arguments: argparse.Namespace,
    value: dict[str, object],
    *,
    exit_code: int = 0,
) -> int:
    if arguments.as_json:
        print(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return exit_code
    if value.get("status") == "REFUSED":
        print("MatchVet fixture observation | RESEARCH_ONLY | REFUSED")
        print(f"Reason: {value['reason']}")
        return exit_code
    print("MatchVet fixture observation | RESEARCH_ONLY")
    print(f"Scope: {value['scope_id']}")
    if "resolved_fixture" in value:
        print(f"Fixture: {value['resolved_fixture']}")
    if "observations" in value:
        observations = value["observations"]
        assert isinstance(observations, list)
        if not observations:
            print("Observations: none")
        for item in observations:
            assert isinstance(item, dict)
            kickoff = item["kickoff_utc"] or item["kickoff_source_date"]
            print(f"{item['resolved_fixture']} | {kickoff} | {item['status']}")
            print(f"Observation digest: {item['observation_digest']}")
            print(f"Artifact digest: {item['artifact_digest']}")
        return exit_code
    kickoff = value["kickoff_utc"] or value["kickoff_source_date"]
    print(f"Kickoff: {value['kickoff_precision']} {kickoff} | {value['status']}")
    print(f"Observation digest: {value['observation_digest']}")
    print(f"Artifact digest: {value['artifact_digest']}")
    return exit_code

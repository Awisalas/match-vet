"""Frozen official Pro League names for the LF05 manual-citation source."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

REGISTRY_VERSION = "matchvet-pro-league-team-alias-registry-v1"
REGISTRY_DIGEST = "sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213"
SOURCE_LINEAGE = "OPERATOR_OFFICIAL_FIXTURE_OBSERVATION"
LEAGUE_KEY = "belgian_pro_league"
SEASON = "2026-27"
OFFICIAL_CALENDAR = "https://www.proleague.be/jpl-kalender!"


@dataclass(frozen=True)
class ApprovedProLeagueAlias:
    league_key: str
    season: str
    source_lineage: str
    source_name: str
    normalized_name: str
    team_id: str
    canonical_name: str
    provenance_type: str
    source_locator: str
    publication_id: str
    confirmation: str


@dataclass(frozen=True)
class ProLeagueTeamAliasRegistry:
    version: str
    digest: str
    entries: tuple[ApprovedProLeagueAlias, ...]

    @classmethod
    def from_json(cls, content: bytes) -> ProLeagueTeamAliasRegistry:
        from matchvet.ingestion import canonical_key, deterministic_identifier

        try:
            payload: Any = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Malformed Pro League registry JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"version", "digest", "entries"}:
            raise ValueError("Invalid Pro League registry envelope")
        if payload["version"] != REGISTRY_VERSION or not isinstance(payload["entries"], list):
            raise ValueError("Unsupported Pro League registry version or entries")
        if not isinstance(payload["digest"], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", payload["digest"]
        ):
            raise ValueError("Invalid Pro League registry digest")
        canonical = json.dumps(
            {"version": payload["version"], "entries": payload["entries"]},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if payload["digest"] != digest or digest != REGISTRY_DIGEST:
            raise ValueError("Pro League registry digest mismatch")
        required = set(ApprovedProLeagueAlias.__dataclass_fields__)
        entries: list[ApprovedProLeagueAlias] = []
        seen_names: set[str] = set()
        seen_targets: set[str] = set()
        for item in payload["entries"]:
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError("Malformed Pro League registry entry")
            if any(not isinstance(value, str) or not value.strip() for value in item.values()):
                raise ValueError("Empty Pro League registry field")
            entry = ApprovedProLeagueAlias(**item)
            expected_id = deterministic_identifier(
                "team", f"{LEAGUE_KEY}:{canonical_key(entry.canonical_name)}"
            )
            if (
                entry.league_key != LEAGUE_KEY
                or entry.season != SEASON
                or entry.source_lineage != SOURCE_LINEAGE
                or entry.provenance_type != "OFFICIAL_COMPETITION_CALENDAR"
                or entry.source_locator != OFFICIAL_CALENDAR
                or entry.publication_id != "jpl-kalender"
                or canonical_key(entry.source_name) != entry.normalized_name
                or entry.team_id != expected_id
            ):
                raise ValueError("Pro League registry scope, provenance, or target is invalid")
            if entry.normalized_name in seen_names or entry.team_id in seen_targets:
                raise ValueError("Duplicate or conflicting Pro League registry entry")
            seen_names.add(entry.normalized_name)
            seen_targets.add(entry.team_id)
            entries.append(entry)
        if entries != sorted(entries, key=lambda entry: entry.normalized_name):
            raise ValueError("Pro League registry entries must be sorted")
        return cls(REGISTRY_VERSION, digest, tuple(entries))

    def candidates(
        self, league_key: str, season: str, lineage: str, source_name: str
    ) -> tuple[ApprovedProLeagueAlias, ...]:
        from matchvet.ingestion import canonical_key

        normalized = canonical_key(source_name)
        return tuple(
            entry
            for entry in self.entries
            if entry.league_key == league_key
            and entry.season == season
            and entry.source_lineage == lineage
            and entry.source_name == source_name
            and entry.normalized_name == normalized
        )


def default_pro_league_registry() -> ProLeagueTeamAliasRegistry:
    return ProLeagueTeamAliasRegistry.from_json(
        files("matchvet").joinpath("pro_league_team_alias_registry_v1.json").read_bytes()
    )

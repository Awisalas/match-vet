"""Reviewed, immutable source-name exceptions for scheduled team identity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from matchvet.ingestion import SourceKind

REGISTRY_VERSION = "matchvet-team-alias-registry-v1"
OPENFOOTBALL_LINEAGE = "openfootball-schedule"


def source_lineage(source_kind: SourceKind) -> str:
    from matchvet.ingestion import SourceKind

    if source_kind in (SourceKind.OPENFOOTBALL, SourceKind.OPENFOOTBALL_TEXT):
        return OPENFOOTBALL_LINEAGE
    return source_kind.value


@dataclass(frozen=True)
class ApprovedAlias:
    league_key: str
    season: str
    source_lineage: str
    source_name: str
    normalized_name: str
    team_id: str
    canonical_name: str
    provenance_type: str
    source_locator: str
    source_revision: str
    source_digest: str
    confirmation: str


@dataclass(frozen=True)
class TeamAliasRegistry:
    version: str
    digest: str
    entries: tuple[ApprovedAlias, ...]

    @classmethod
    def from_json(cls, content: bytes) -> TeamAliasRegistry:
        from matchvet.ingestion import canonical_key, deterministic_identifier, league_by_key

        try:
            payload: Any = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Malformed team alias registry JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"version", "digest", "entries"}:
            raise ValueError("Invalid team alias registry envelope")
        if payload["version"] != REGISTRY_VERSION or not isinstance(payload["entries"], list):
            raise ValueError("Unsupported team alias registry version or entries")
        if not isinstance(payload["digest"], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", payload["digest"]
        ):
            raise ValueError("Invalid team alias registry digest")
        canonical_payload = json.dumps(
            {"version": payload["version"], "entries": payload["entries"]},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = f"sha256:{hashlib.sha256(canonical_payload.encode()).hexdigest()}"
        if payload["digest"] != digest:
            raise ValueError("Team alias registry digest mismatch")
        required = set(ApprovedAlias.__dataclass_fields__)
        entries: list[ApprovedAlias] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in payload["entries"]:
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError("Malformed team alias registry entry")
            if any(not isinstance(value, str) or not value.strip() for value in item.values()):
                raise ValueError("Empty team alias registry field")
            entry = ApprovedAlias(**item)
            league_by_key(entry.league_key)
            if canonical_key(entry.source_name) != entry.normalized_name:
                raise ValueError("Alias normalized name does not match frozen normalization")
            expected_id = deterministic_identifier(
                "team", f"{entry.league_key}:{canonical_key(entry.canonical_name)}"
            )
            if entry.team_id != expected_id:
                raise ValueError("Alias target ID does not match canonical team identity")
            if (
                not re.fullmatch(r"20\d{2}-\d{2}", entry.season)
                or not entry.source_locator.startswith("https://")
                or not re.fullmatch(r"[0-9a-f]{40}", entry.source_revision)
                or not re.fullmatch(r"[0-9a-f]{64}", entry.source_digest)
                or entry.source_revision not in entry.source_locator
                or not re.search(r"#L[1-9][0-9]*$", entry.source_locator)
                or entry.source_lineage != OPENFOOTBALL_LINEAGE
                or entry.provenance_type != "OPENFOOTBALL_CLUBS_CANDIDATE"
            ):
                raise ValueError("Alias scope or confirmation is invalid")
            key = (
                entry.league_key,
                entry.season,
                entry.source_lineage,
                entry.normalized_name,
            )
            if key in seen:
                raise ValueError("Duplicate or conflicting team alias registry entry")
            seen.add(key)
            entries.append(entry)
        if entries != sorted(
            entries,
            key=lambda item: (
                item.league_key,
                item.season,
                item.source_lineage,
                item.normalized_name,
            ),
        ):
            raise ValueError("Team alias registry entries must be sorted")
        return cls(REGISTRY_VERSION, digest, tuple(entries))

    def candidates(
        self, league_key: str, season: str, lineage: str, source_name: str
    ) -> tuple[ApprovedAlias, ...]:
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


def default_registry() -> TeamAliasRegistry:
    return TeamAliasRegistry.from_json(
        files("matchvet").joinpath("team_alias_registry_v1.json").read_bytes()
    )

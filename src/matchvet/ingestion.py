"""T06 fixture and structured match-history acquisition.

This module deliberately stops at source-backed facts. It does not freeze a
Matchweek, research contextual evidence, or calculate a prediction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import re
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from matchvet.artifacts import ArtifactStore
from matchvet.runs import (
    MIB,
    SETTLED_RESOURCE_BUDGET,
    ResourceBudget,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunPhase,
    RunStatus,
    WorkContext,
    WorkResult,
)
from matchvet.store import MIGRATIONS, CanonicalIdentifier, Store, StoreTransaction


class EvidenceState(StrEnum):
    OBSERVED = "OBSERVED"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


OBSERVED = EvidenceState.OBSERVED
ABSENT = EvidenceState.ABSENT
UNKNOWN = EvidenceState.UNKNOWN


class SourceKind(StrEnum):
    FOOTBALL_DATA = "FOOTBALL_DATA"
    OPENFOOTBALL = "OPENFOOTBALL"


class MappingState(StrEnum):
    CONFIRMED = "CONFIRMED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class IngestionError(Exception):
    """Base class for bounded T06 acquisition failures."""


class SourceParseError(IngestionError):
    """The source document cannot be structurally parsed."""


class SourcePolicyError(IngestionError):
    """The requested source or field is outside the settled source policy."""


class SourceUnavailable(IngestionError):
    """An approved source could not be retrieved."""


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    name: str
    country: str
    football_data_code: str
    openfootball_code: str | None
    timezone: str

    @property
    def openfootball_supported(self) -> bool:
        return self.openfootball_code is not None


TARGET_LEAGUES: tuple[LeagueConfig, ...] = (
    LeagueConfig("premier_league", "Premier League", "England", "E0", "en.1", "Europe/London"),
    LeagueConfig("serie_a", "Serie A", "Italy", "I1", "it.1", "Europe/Rome"),
    LeagueConfig("la_liga", "La Liga", "Spain", "SP1", "es.1", "Europe/Madrid"),
    LeagueConfig("bundesliga", "Bundesliga", "Germany", "D1", "de.1", "Europe/Berlin"),
    LeagueConfig("ligue_1", "Ligue 1", "France", "F1", "fr.1", "Europe/Paris"),
    LeagueConfig("liga_portugal", "Liga Portugal", "Portugal", "P1", "pt.1", "Europe/Lisbon"),
    LeagueConfig(
        "belgian_pro_league",
        "Belgian Pro League",
        "Belgium",
        "B1",
        None,
        "Europe/Brussels",
    ),
)

_LEAGUES_BY_KEY = MappingProxyType({league.key: league for league in TARGET_LEAGUES})
_LEAGUES_BY_NAME = MappingProxyType({league.name.casefold(): league for league in TARGET_LEAGUES})
_SOURCE_NAMESPACE = uuid.UUID("f4d7e4fc-0f4e-5a1a-9d89-06f8cae63c9b")
_SEASON_PATTERN = re.compile(r"^(?P<start>20\d{2})-(?P<end>\d{2})$")
_INTEGER_PATTERN = re.compile(r"^\d+$")
_HEADER_PATTERN = re.compile(r"[^a-z0-9]+")


def _header_key(value: str) -> str:
    return _HEADER_PATTERN.sub("", value.strip().casefold())


def league_by_key(key: str) -> LeagueConfig:
    try:
        return _LEAGUES_BY_KEY[key]
    except KeyError as error:
        raise KeyError(f"Unknown configured Target League: {key}") from error


def league_by_name(name: str) -> LeagueConfig:
    try:
        return _LEAGUES_BY_NAME[name.casefold()]
    except KeyError as error:
        raise KeyError(f"Unknown configured Target League: {name}") from error


def season_code(season: str) -> str:
    match = _SEASON_PATTERN.fullmatch(season)
    if match is None:
        raise ValueError("Season must use YYYY-YY form, for example 2026-27.")
    return match.group("start")[2:] + match.group("end")


def football_data_url(league: LeagueConfig, season: str) -> str:
    return (
        "https://www.football-data.co.uk/mmz4281/"
        f"{season_code(season)}/{league.football_data_code}.csv"
    )


def openfootball_url(league: LeagueConfig, season: str) -> str:
    if league.openfootball_code is None:
        raise SourcePolicyError(f"OpenFootball has no permitted fallback for {league.name}.")
    return (
        "https://raw.githubusercontent.com/openfootball/football.json/master/"
        f"{season}/{league.openfootball_code}.json"
    )


def canonical_key(value: str) -> str:
    """Normalize a source name for deterministic matching, not display."""
    normalized = value.strip().casefold()
    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("'", "")
    normalized = re.sub(r"\b(fc|afc|cf|ac|ss|1\.?\s*fc)\b", " ", normalized)
    normalized = _HEADER_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return {
        "coventry city": "coventry",
        "leeds united": "leeds",
        "west ham united": "west ham",
        "manchester united": "man united",
        "manchester city": "man city",
        "tottenham hotspur": "tottenham",
        "wolverhampton wanderers": "wolves",
        "brighton and hove albion": "brighton",
        "nottingham forest": "nottingham",
    }.get(normalized, normalized)


def deterministic_identifier(kind: str, key: str) -> str:
    """Return the stable UUID value used for one canonical T06 identity."""
    return str(uuid.uuid5(_SOURCE_NAMESPACE, f"{kind}:{key}"))


@dataclass(frozen=True)
class ParsedField:
    name: str
    state: EvidenceState
    value: int | str | None = None
    raw_value: str | None = None
    unknown_reason: str | None = None
    evidence_class: str = "CORE"
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.state is EvidenceState.OBSERVED and self.value is None:
            raise ValueError("Observed parsed fields require a value.")
        if self.state is EvidenceState.UNKNOWN and not self.unknown_reason:
            raise ValueError("Unknown parsed fields require a reason.")
        if self.state is EvidenceState.ABSENT and self.value is not None:
            raise ValueError("Absent parsed fields cannot contain a value.")


@dataclass(frozen=True)
class ParsedRow:
    source_row_key: str
    home_team: str
    away_team: str
    kickoff_utc: datetime | None
    kickoff_local_date: date | None
    kickoff_local_text: str | None
    kickoff_precision: str
    fields: Mapping[str, ParsedField]
    raw_fields: Mapping[str, str]
    source_round: str | None = None
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDataset:
    source_kind: SourceKind
    league: LeagueConfig
    season: str
    rows: tuple[ParsedRow, ...]
    source_variant: str

    def __iter__(self) -> Iterator[ParsedRow]:
        return iter(self.rows)


_STAT_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("FTHG", "full_time_home_goals", "home", "FULL_MATCH", "goals"),
    ("FTAG", "full_time_away_goals", "away", "FULL_MATCH", "goals"),
    ("HTHG", "half_time_home_goals", "home", "FIRST_HALF", "goals"),
    ("HTAG", "half_time_away_goals", "away", "FIRST_HALF", "goals"),
    ("HS", "shots_home", "home", "FULL_MATCH", "shots"),
    ("AS", "shots_away", "away", "FULL_MATCH", "shots"),
    ("HST", "shots_on_target_home", "home", "FULL_MATCH", "shots_on_target"),
    ("AST", "shots_on_target_away", "away", "FULL_MATCH", "shots_on_target"),
    ("HF", "fouls_home", "home", "FULL_MATCH", "fouls"),
    ("AF", "fouls_away", "away", "FULL_MATCH", "fouls"),
    ("HC", "corners_home", "home", "FULL_MATCH", "corners"),
    ("AC", "corners_away", "away", "FULL_MATCH", "corners"),
    ("HY", "yellow_cards_home", "home", "FULL_MATCH", "cards"),
    ("AY", "yellow_cards_away", "away", "FULL_MATCH", "cards"),
    ("HR", "red_cards_home", "home", "FULL_MATCH", "cards"),
    ("AR", "red_cards_away", "away", "FULL_MATCH", "cards"),
)

_ALLOWED_METADATA_FIELDS = frozenset(
    {"Div", "Date", "Time", "HomeTeam", "AwayTeam", "Round", "FTR", "HTR"}
)
_OPTIONAL_XG_FIELDS = {
    "hxg": "home_xg",
    "axg": "away_xg",
    "homexg": "home_xg",
    "awayxg": "away_xg",
    "xghome": "home_xg",
    "xgaway": "away_xg",
}
_POLICY_HEADER_KEYS = frozenset(
    {
        *(_header_key(name) for name in _ALLOWED_METADATA_FIELDS),
        *(_header_key(source_name) for source_name, *_ in _STAT_SPECS),
        *_OPTIONAL_XG_FIELDS,
    }
)


def _parse_integer(name: str, raw: str | None) -> ParsedField:
    if raw is None or not raw.strip():
        return ParsedField(name, UNKNOWN, raw_value=raw, unknown_reason="SOURCE_MISSING_FIELD")
    value = raw.strip()
    if _INTEGER_PATTERN.fullmatch(value) is None:
        return ParsedField(name, UNKNOWN, raw_value=raw, unknown_reason="MALFORMED_VALUE")
    return ParsedField(name, OBSERVED, int(value), raw_value=raw, unit="count")


def _parse_result(name: str, raw: str | None) -> ParsedField:
    if raw is None or not raw.strip():
        return ParsedField(name, UNKNOWN, raw_value=raw, unknown_reason="SOURCE_MISSING_FIELD")
    value = raw.strip().upper()
    if value not in {"H", "D", "A"}:
        return ParsedField(name, UNKNOWN, raw_value=raw, unknown_reason="MALFORMED_VALUE")
    return ParsedField(name, OBSERVED, value, raw_value=raw)


def _parse_decimal(name: str, raw: str | None) -> ParsedField:
    if raw is None or not raw.strip():
        return ParsedField(
            name,
            UNKNOWN,
            raw_value=raw,
            unknown_reason="SOURCE_MISSING_FIELD",
            evidence_class="OPTIONAL_EVIDENCE",
        )
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return ParsedField(
            name,
            UNKNOWN,
            raw_value=raw,
            unknown_reason="MALFORMED_VALUE",
            evidence_class="OPTIONAL_EVIDENCE",
        )
    if not value.is_finite() or value < 0:
        return ParsedField(
            name,
            UNKNOWN,
            raw_value=raw,
            unknown_reason="MALFORMED_VALUE",
            evidence_class="OPTIONAL_EVIDENCE",
        )
    return ParsedField(
        name,
        OBSERVED,
        format(value, "f"),
        raw_value=raw,
        evidence_class="OPTIONAL_EVIDENCE",
        unit="expected_goals",
    )


def _parse_date(raw: str | None) -> date | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _parse_time(raw: str | None) -> time | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).time()
        except ValueError:
            continue
    return None


def _kickoff(
    league: LeagueConfig,
    date_raw: str | None,
    time_raw: str | None,
) -> tuple[datetime | None, date | None, str | None, str, tuple[str, ...]]:
    local_date = _parse_date(date_raw)
    warnings: list[str] = []
    if date_raw and local_date is None:
        warnings.append("MALFORMED_DATE")
    if local_date is None:
        return None, None, None, "UNKNOWN", tuple(warnings)
    local_time = _parse_time(time_raw)
    if time_raw and local_time is None:
        warnings.append("MALFORMED_TIME")
    if local_time is None:
        return None, local_date, date_raw.strip() if date_raw else None, "DATE", tuple(warnings)
    local = datetime.combine(local_date, local_time, _source_timezone(league.timezone, local_date))
    return local.astimezone(UTC), local_date, local.isoformat(), "INSTANT", tuple(warnings)


def _source_timezone(name: str, local_date: date) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        base_hours = {
            "Europe/London": 0,
            "Europe/Lisbon": 0,
            "Europe/Rome": 1,
            "Europe/Madrid": 1,
            "Europe/Berlin": 1,
            "Europe/Paris": 1,
            "Europe/Brussels": 1,
        }.get(name)
        if base_hours is None:
            raise SourceParseError(f"Unknown configured timezone {name}.") from None
        daylight = 1 if _european_summer_time(local_date) else 0
        return timezone(timedelta(hours=base_hours + daylight))


def _european_summer_time(value: date) -> bool:
    march_last = date(value.year, 4, 1) - timedelta(days=1)
    october_last = date(value.year, 11, 1) - timedelta(days=1)
    march_start = march_last - timedelta(days=(march_last.weekday() - 6) % 7)
    october_end = october_last - timedelta(days=(october_last.weekday() - 6) % 7)
    return march_start <= value < october_end


class FootballDataCSVParser:
    """Parse only the settled Football-Data structured fields."""

    def parse(
        self,
        content: bytes | str,
        *,
        league: LeagueConfig,
        season: str,
    ) -> ParsedDataset:
        if isinstance(content, bytes):
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
        else:
            text = content
        if not text.strip():
            raise SourceParseError("Football-Data CSV is empty.")
        delimiter = _csv_delimiter(text)
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
        if reader.fieldnames is None:
            raise SourceParseError("Football-Data CSV has no header row.")
        fieldnames = tuple((name or "").strip().lstrip("\ufeff") for name in reader.fieldnames)
        normalized_headers = tuple(_header_key(name) for name in fieldnames)
        policy_headers = [
            normalized for normalized in normalized_headers if normalized in _POLICY_HEADER_KEYS
        ]
        if len(set(policy_headers)) != len(policy_headers):
            raise SourceParseError("Football-Data CSV contains duplicate header names.")
        required = {"hometeam", "awayteam"}
        if not required.issubset(normalized_headers):
            raise SourceParseError(
                "Football-Data CSV lacks required HomeTeam and AwayTeam columns."
            )
        try:
            raw_rows = list(reader)
        except csv.Error as error:
            raise SourceParseError("Football-Data CSV is structurally malformed.") from error
        rows: list[ParsedRow] = []
        for line_number, raw_row in enumerate(raw_rows, start=2):
            row = {
                fieldnames[index]: (value if value is not None else "")
                for index, value in enumerate(raw_row.values())
                if index < len(fieldnames)
            }
            home = _value_for(row, normalized_headers, fieldnames, "hometeam")
            away = _value_for(row, normalized_headers, fieldnames, "awayteam")
            if not home.strip() or not away.strip():
                raise SourceParseError(f"Football-Data row {line_number} has an empty team name.")
            date_raw = _value_for(row, normalized_headers, fieldnames, "date")
            time_raw = _value_for(row, normalized_headers, fieldnames, "time")
            kickoff, local_date, local_text, precision, warnings = _kickoff(
                league, date_raw, time_raw
            )
            fields: dict[str, ParsedField] = {}
            for source_name, metric_name, _role, _phase, unit in _STAT_SPECS:
                raw = _value_for_optional(
                    row, normalized_headers, fieldnames, _header_key(source_name)
                )
                parsed = _parse_integer(metric_name, raw)
                fields[metric_name] = ParsedField(
                    parsed.name,
                    parsed.state,
                    parsed.value,
                    parsed.raw_value,
                    parsed.unknown_reason,
                    parsed.evidence_class,
                    unit,
                )
            for source_name, metric_name in (
                ("ftr", "full_time_result"),
                ("htr", "half_time_result"),
            ):
                fields[metric_name] = _parse_result(
                    metric_name,
                    _value_for_optional(row, normalized_headers, fieldnames, source_name),
                )
            for source_key, metric_name in _OPTIONAL_XG_FIELDS.items():
                if source_key in normalized_headers:
                    fields[metric_name] = _parse_decimal(
                        metric_name,
                        _value_for_optional(row, normalized_headers, fieldnames, source_key),
                    )
            raw_fields = {
                fieldnames[index]: value
                for index, value in enumerate(raw_row.values())
                if index < len(fieldnames)
                and _is_allowed_source_field(fieldnames[index], normalized_headers[index])
            }
            rows.append(
                ParsedRow(
                    source_row_key=f"row-{line_number}",
                    home_team=home.strip(),
                    away_team=away.strip(),
                    kickoff_utc=kickoff,
                    kickoff_local_date=local_date,
                    kickoff_local_text=local_text,
                    kickoff_precision=precision,
                    fields=MappingProxyType(fields),
                    raw_fields=MappingProxyType(raw_fields),
                    source_round=_value_for_optional(row, normalized_headers, fieldnames, "round")
                    or None,
                    parse_warnings=warnings,
                )
            )
        return ParsedDataset(
            SourceKind.FOOTBALL_DATA, league, season, tuple(rows), "football-data-csv"
        )


def _csv_delimiter(text: str) -> str:
    header = text.splitlines()[0]
    candidates = {delimiter: header.count(delimiter) for delimiter in (",", ";", "\t")}
    delimiter, count = max(candidates.items(), key=lambda item: item[1])
    if count == 0:
        raise SourceParseError("Football-Data CSV has no supported delimiter.")
    return delimiter


def _value_for(
    row: Mapping[str, str], normalized: Sequence[str], headers: Sequence[str], key: str
) -> str:
    return _value_for_optional(row, normalized, headers, key) or ""


def _value_for_optional(
    row: Mapping[str, str], normalized: Sequence[str], headers: Sequence[str], key: str
) -> str | None:
    for index, normalized_name in enumerate(normalized):
        if normalized_name == key:
            return row.get(headers[index], "")
    return None


def _is_allowed_source_field(name: str, normalized: str) -> bool:
    if normalized in {_header_key(metadata_name) for metadata_name in _ALLOWED_METADATA_FIELDS}:
        return True
    if normalized in {_header_key(source_name) for source_name, *_ in _STAT_SPECS}:
        return True
    return normalized in _OPTIONAL_XG_FIELDS


class OpenFootballJSONParser:
    """Parse OpenFootball's CC0 fixture/result JSON fallback."""

    def parse(
        self,
        content: bytes | str,
        *,
        league: LeagueConfig,
        season: str,
    ) -> ParsedDataset:
        if league.openfootball_code is None:
            raise SourcePolicyError(f"OpenFootball has no permitted fallback for {league.name}.")
        try:
            text = content.decode("utf-8") if isinstance(content, bytes) else content
            loaded: object = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceParseError("OpenFootball JSON is malformed.") from error
        if not isinstance(loaded, dict):
            raise SourceParseError("OpenFootball JSON root must be an object.")
        matches = loaded.get("matches")
        if not isinstance(matches, list):
            raise SourceParseError("OpenFootball JSON must contain a matches array.")
        rows: list[ParsedRow] = []
        for index, item in enumerate(matches, start=1):
            if not isinstance(item, dict):
                raise SourceParseError(f"OpenFootball match {index} is not an object.")
            home = _openfootball_team(item.get("team1"))
            away = _openfootball_team(item.get("team2"))
            if not home or not away:
                raise SourceParseError(f"OpenFootball match {index} has no two team names.")
            date_raw = _object_string(item.get("date"))
            time_raw = _object_string(item.get("time"))
            kickoff, local_date, local_text, precision, warnings = _kickoff(
                league, date_raw, time_raw
            )
            score = item.get("score")
            score_map = score if isinstance(score, dict) else {}
            fields = _openfootball_fields(score_map)
            raw_fields = {
                key: _json_scalar(value)
                for key, value in item.items()
                if key in {"round", "date", "time", "team1", "team2", "score"}
            }
            rows.append(
                ParsedRow(
                    source_row_key=f"match-{index}",
                    home_team=home,
                    away_team=away,
                    kickoff_utc=kickoff,
                    kickoff_local_date=local_date,
                    kickoff_local_text=local_text,
                    kickoff_precision=precision,
                    fields=MappingProxyType(fields),
                    raw_fields=MappingProxyType(raw_fields),
                    source_round=_object_string(item.get("round")) or None,
                    parse_warnings=warnings,
                )
            )
        return ParsedDataset(
            SourceKind.OPENFOOTBALL, league, season, tuple(rows), "openfootball-json"
        )


def _openfootball_team(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name")
        return name.strip() if isinstance(name, str) else ""
    return ""


def _object_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _json_scalar(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _openfootball_fields(score: Mapping[object, object]) -> dict[str, ParsedField]:
    fields: dict[str, ParsedField] = {}
    for source_name, metric_name, _role, _phase, unit in _STAT_SPECS:
        del source_name
        fields[metric_name] = ParsedField(
            metric_name,
            UNKNOWN,
            unknown_reason="SOURCE_OUTSIDE_COVERAGE",
            unit=unit,
        )
    for result_name in ("full_time_result", "half_time_result"):
        fields[result_name] = ParsedField(
            result_name,
            UNKNOWN,
            unknown_reason="SOURCE_OUTSIDE_COVERAGE",
        )
    for score_key, home_name, away_name in (
        ("ft", "full_time_home_goals", "full_time_away_goals"),
        ("ht", "half_time_home_goals", "half_time_away_goals"),
    ):
        pair = score.get(score_key)
        home = _openfootball_score_field(home_name, pair, 0)
        away = _openfootball_score_field(away_name, pair, 1)
        fields[home_name] = home
        fields[away_name] = away
        if home.state is OBSERVED and away.state is OBSERVED:
            result_name = "full_time_result" if score_key == "ft" else "half_time_result"
            assert isinstance(home.value, int)
            assert isinstance(away.value, int)
            result = "H" if home.value > away.value else "A" if home.value < away.value else "D"
            fields[result_name] = ParsedField(result_name, OBSERVED, result)
    return fields


def _openfootball_score_field(name: str, pair: object, index: int) -> ParsedField:
    if pair is None:
        return ParsedField(name, UNKNOWN, unknown_reason="SOURCE_MISSING_FIELD")
    if not isinstance(pair, list) or len(pair) != 2:
        return ParsedField(name, UNKNOWN, unknown_reason="MALFORMED_VALUE")
    value = pair[index]
    if isinstance(value, bool):
        return ParsedField(name, UNKNOWN, unknown_reason="MALFORMED_VALUE")
    if isinstance(value, int) and value >= 0:
        return ParsedField(name, OBSERVED, value, raw_value=str(value), unit="goals")
    if isinstance(value, str) and _INTEGER_PATTERN.fullmatch(value.strip()):
        return ParsedField(name, OBSERVED, int(value.strip()), raw_value=value, unit="goals")
    return ParsedField(name, UNKNOWN, unknown_reason="MALFORMED_VALUE")


class TeamResolver(Protocol):
    def resolve(self, league: LeagueConfig, source_name: str) -> TeamResolution: ...


@dataclass(frozen=True)
class TeamResolution:
    state: MappingState
    source_name: str
    canonical_team_id: str | None
    canonical_name: str | None
    candidates: tuple[str, ...] = ()


@dataclass
class TeamCanonicalizer:
    """Deterministic name/alias mapping used by both approved source adapters."""

    _canonical_names: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    _aliases: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def register_team(self, league: LeagueConfig, canonical_name: str, *aliases: str) -> str:
        normalized = canonical_key(canonical_name)
        team_id = deterministic_identifier("team", f"{league.key}:{normalized}")
        self._canonical_names[(league.key, team_id)] = (team_id, canonical_name)
        for alias in (canonical_name, *aliases):
            self.register_alias(league, alias, team_id)
        return team_id

    def register_alias(self, league: LeagueConfig, alias: str, canonical_team_id: str) -> None:
        key = (league.key, canonical_key(alias))
        self._aliases.setdefault(key, set()).add(canonical_team_id)

    def resolve(self, league: LeagueConfig, source_name: str) -> TeamResolution:
        normalized = canonical_key(source_name)
        candidates = tuple(sorted(self._aliases.get((league.key, normalized), set())))
        if len(candidates) == 1:
            team_id = candidates[0]
            return TeamResolution(
                MappingState.CONFIRMED,
                source_name,
                team_id,
                self._canonical_names.get((league.key, team_id), (team_id, source_name))[1],
                candidates,
            )
        if len(candidates) > 1:
            return TeamResolution(MappingState.AMBIGUOUS, source_name, None, None, candidates)
        return TeamResolution(MappingState.UNKNOWN, source_name, None, None)

    def resolve_or_register(self, league: LeagueConfig, source_name: str) -> TeamResolution:
        resolved = self.resolve(league, source_name)
        if resolved.state is not MappingState.UNKNOWN:
            return resolved
        team_id = self.register_team(league, source_name)
        return TeamResolution(MappingState.CONFIRMED, source_name, team_id, source_name)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def sha256_bytes(content: bytes) -> str:

    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class SourceCaptureInput:
    source_url: str
    retrieved_at_utc: str
    observed_terms: str
    source_published_at_utc: str | None = None
    response_status: int = 200
    content_type: str | None = None
    cache_key: str | None = None


@dataclass(frozen=True)
class SourceCaptureRecord:
    capture_id: str
    source_id: str
    source_key: str
    locator: str
    retrieved_at_utc: str
    content_sha256: str
    byte_length: int
    artifact_digest: str
    allowed_use: str
    retention_status: str
    redistributable: bool
    observed_terms: str
    terms_reference: str


@dataclass(frozen=True)
class FixtureRecord:
    fixture_id: str
    league_key: str
    season: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    identity_state: str


@dataclass(frozen=True)
class FixtureRevisionRecord:
    revision_id: str
    fixture_id: str
    predecessor_revision_id: str | None
    revision_digest: str
    kickoff_state: EvidenceState
    kickoff_utc: str | None
    kickoff_local_text: str | None
    kickoff_precision: str
    fixture_status: str
    source_round: str | None
    observed_at_utc: str


@dataclass(frozen=True)
class MatchStatisticRecord:
    statistic_id: str
    fixture_id: str
    metric_key: str
    team_role: str
    phase: str
    evidence_class: str
    state: EvidenceState
    value_integer: int | None
    value_text: str | None
    unit: str | None
    unknown_reason: str | None
    source_assertion_id: str


@dataclass(frozen=True)
class SourceAssertionRecord:
    assertion_id: str
    capture_id: str
    source_row_key: str
    subject_kind: str
    subject_key: str
    evidence_type: str
    predicate: str
    raw_field_name: str
    evidence_state: EvidenceState
    raw_value_json: str | None
    normalized_value_json: str | None
    unknown_reason: str | None


@dataclass(frozen=True)
class ConflictRecord:
    conflict_id: str
    subject_key: str
    predicate: str
    value_digest: str
    status: str
    assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    source_capture_id: str
    source_digest: str
    league_key: str
    season: str
    fixtures_seen: int
    fixtures_imported: int
    revisions_appended: int
    statistics_imported: int
    unknown_fields: int
    duplicate_rows: int
    unresolved_rows: int
    conflicts: int
    from_existing_capture: bool = False


@dataclass(frozen=True)
class _SourceRights:
    source_key: str
    canonical_name: str
    owner: str
    source_class: str
    access_method: str
    base_locator: str
    allowed_use: str
    retention_status: str
    redistributable: bool
    terms_reference: str
    artifact_retention_class: str


_SOURCE_RIGHTS: Mapping[SourceKind, _SourceRights] = MappingProxyType(
    {
        SourceKind.FOOTBALL_DATA: _SourceRights(
            source_key="football-data.co.uk",
            canonical_name="Football-Data.co.uk",
            owner="Football-Data.co.uk",
            source_class="STRUCTURED_PROVIDER",
            access_method="DIRECT_CSV",
            base_locator="https://www.football-data.co.uk/",
            allowed_use="RESTRICTED_PRIVATE",
            retention_status="RETAIN_PRIVATE",
            redistributable=False,
            terms_reference=(
                "CONTEXT.md: Football-Data.co.uk restricted private local noncommercial use"
            ),
            artifact_retention_class="PROTECTED",
        ),
        SourceKind.OPENFOOTBALL: _SourceRights(
            source_key="openfootball",
            canonical_name="OpenFootball football.json",
            owner="OpenFootball",
            source_class="OPEN_DATASET",
            access_method="DIRECT_RAW_JSON",
            base_locator="https://raw.githubusercontent.com/openfootball/football.json/",
            allowed_use="CC0",
            retention_status="RETAIN_REUSABLE",
            redistributable=True,
            terms_reference="https://creativecommons.org/publicdomain/zero/1.0/",
            artifact_retention_class="REUSABLE",
        ),
    }
)


_FIELD_META: Mapping[str, tuple[str, str, str]] = MappingProxyType(
    {
        metric_name: (role, phase, unit)
        for _source_name, metric_name, role, phase, unit in _STAT_SPECS
    }
    | {
        "full_time_result": ("match", "FULL_MATCH", "result"),
        "half_time_result": ("match", "FIRST_HALF", "result"),
        "home_xg": ("home", "FULL_MATCH", "expected_goals"),
        "away_xg": ("away", "FULL_MATCH", "expected_goals"),
    }
)
_RAW_FIELD_NAMES: Mapping[str, str] = MappingProxyType(
    {metric_name: source_name for source_name, metric_name, _role, _phase, _unit in _STAT_SPECS}
    | {
        "full_time_result": "FTR",
        "half_time_result": "HTR",
        "home_xg": "HxG",
        "away_xg": "AxG",
    }
)


class FixtureHistoryImporter:
    """Import one parsed approved source capture in one normalized transaction."""

    def __init__(
        self,
        store: Store,
        *,
        private_root: Path,
        team_canonicalizer: TeamCanonicalizer | None = None,
    ) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Fixture history import requires a healthy writable store.")
        self._store = store
        self._private_root = private_root.resolve()
        self._teams = team_canonicalizer or TeamCanonicalizer()
        self._artifacts = ArtifactStore(store)

    def import_dataset(
        self,
        dataset: ParsedDataset,
        content: bytes,
        capture: SourceCaptureInput,
        *,
        failure_hook: Callable[[int], None] | None = None,
    ) -> ImportResult:
        if not isinstance(content, bytes):
            raise TypeError("Source content must be bytes.")
        if not capture.source_url or not capture.observed_terms:
            raise ValueError("Source URL and observed terms are required.")
        source_rights = _SOURCE_RIGHTS[dataset.source_kind]
        captured_at = _canonical_utc(capture.retrieved_at_utc)
        source_id = deterministic_identifier("source", source_rights.source_key)
        digest = sha256_bytes(content)
        cache_key = capture.cache_key or (
            f"{source_rights.source_key}:{dataset.league.key}:{dataset.season}:{capture.source_url}"
        )
        existing = self._existing_capture(source_id, cache_key, digest, captured_at)
        if existing is not None:
            return ImportResult(
                existing.capture_id,
                digest,
                dataset.league.key,
                dataset.season,
                len(dataset.rows),
                0,
                0,
                0,
                0,
                len(dataset.rows),
                0,
                True,
            )
        if (
            dataset.source_kind is SourceKind.FOOTBALL_DATA
            and capture.observed_terms.strip().upper() == "CC0"
        ):
            raise SourcePolicyError("Football-Data captures cannot be labeled CC0.")
        media_type = capture.content_type or (
            "text/csv" if dataset.source_kind is SourceKind.FOOTBALL_DATA else "application/json"
        )
        artifact = self._artifacts.publish_artifact(
            content,
            media_type,
            expected_digest=digest,
            retention_class=source_rights.artifact_retention_class,
        )
        capture_id = deterministic_identifier(
            "source_capture", f"{source_id}:{cache_key}:{digest}:{captured_at}"
        )
        origin_id = deterministic_identifier("origin", source_rights.source_key)
        league_id = deterministic_identifier("league", dataset.league.key)
        season_id = deterministic_identifier(
            "competition_season", f"{dataset.league.key}:{dataset.season}"
        )
        counters = {
            "fixtures_imported": 0,
            "revisions_appended": 0,
            "statistics_imported": 0,
            "unknown_fields": 0,
            "duplicate_rows": 0,
            "unresolved_rows": 0,
        }
        with self._store.transaction() as transaction:
            self._ensure_source(transaction, source_id, source_rights, captured_at)
            self._ensure_origin(transaction, origin_id, source_rights)
            self._ensure_league(transaction, league_id, dataset.league, captured_at)
            self._ensure_season(transaction, season_id, league_id, dataset.season, captured_at)
            transaction.add_identifier_if_missing(
                CanonicalIdentifier(kind="source_capture", value=capture_id)
            )
            transaction.execute(
                """
                INSERT INTO source_captures (
                    capture_id, source_id, cache_key, locator, access_method,
                    retrieved_at_utc, source_published_at_utc, response_status,
                    content_type, content_sha256, byte_length, artifact_digest,
                    retention_status, observed_terms, terms_reference, rights_json,
                    collector_version, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    source_id,
                    cache_key,
                    capture.source_url,
                    source_rights.access_method,
                    captured_at,
                    _optional_utc(capture.source_published_at_utc),
                    capture.response_status,
                    media_type,
                    digest,
                    len(content),
                    artifact.digest,
                    source_rights.retention_status,
                    capture.observed_terms,
                    source_rights.terms_reference,
                    _canonical_json(
                        {
                            "allowed_use": source_rights.allowed_use,
                            "redistributable": source_rights.redistributable,
                            "retention_status": source_rights.retention_status,
                            "source_kind": dataset.source_kind.value,
                        }
                    ).decode("utf-8"),
                    "matchvet-t06-v1",
                    captured_at,
                ),
            )
            seen_row_fingerprints: set[str] = set()
            for row_number, row in enumerate(dataset.rows, start=1):
                if failure_hook is not None:
                    failure_hook(row_number)
                row_fingerprint = sha256_bytes(
                    _canonical_json(
                        {
                            "home": row.home_team,
                            "away": row.away_team,
                            "kickoff": _raw_kickoff(row),
                            "fields": {
                                key: (
                                    field.state.value,
                                    field.value,
                                    field.raw_value,
                                    field.unknown_reason,
                                )
                                for key, field in sorted(row.fields.items())
                            },
                        }
                    )
                )
                if row_fingerprint in seen_row_fingerprints:
                    counters["duplicate_rows"] += 1
                    continue
                seen_row_fingerprints.add(row_fingerprint)
                if self._row_already_imported(transaction, capture_id, row.source_row_key):
                    counters["duplicate_rows"] += 1
                    continue
                self._import_row(
                    transaction,
                    dataset,
                    row,
                    capture_id,
                    source_id,
                    league_id,
                    season_id,
                    origin_id,
                    captured_at,
                    counters,
                )
        conflict_count = self._count_conflicts_for_dataset(dataset, league_id, season_id)
        return ImportResult(
            capture_id,
            digest,
            dataset.league.key,
            dataset.season,
            len(dataset.rows),
            counters["fixtures_imported"],
            counters["revisions_appended"],
            counters["statistics_imported"],
            counters["unknown_fields"],
            counters["duplicate_rows"],
            counters["unresolved_rows"],
            conflict_count,
        )

    def fixtures(self) -> tuple[FixtureRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT f.fixture_id, l.league_key, s.season_label,
                   f.home_team_id, f.away_team_id,
                   home.canonical_name, away.canonical_name, f.identity_state
            FROM fixtures AS f
            JOIN target_leagues AS l ON l.league_id = f.league_id
            JOIN competition_seasons AS s ON s.season_id = f.season_id
            JOIN teams AS home ON home.team_id = f.home_team_id
            JOIN teams AS away ON away.team_id = f.away_team_id
            ORDER BY l.league_key, s.season_label, f.fixture_id
            """
        ).fetchall()
        return tuple(FixtureRecord(*[str(value) for value in row]) for row in rows)

    def revisions(self, fixture_id: str) -> tuple[FixtureRevisionRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT revision_id, fixture_id, predecessor_revision_id, revision_digest,
                   kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
                   fixture_status, source_round, observed_at_utc
            FROM fixture_revisions
            WHERE fixture_id = ?
            ORDER BY observed_at_utc, revision_id
            """,
            (fixture_id,),
        ).fetchall()
        return tuple(
            FixtureRevisionRecord(
                revision_id=str(row[0]),
                fixture_id=str(row[1]),
                predecessor_revision_id=str(row[2]) if row[2] is not None else None,
                revision_digest=str(row[3]),
                kickoff_state=EvidenceState(str(row[4])),
                kickoff_utc=str(row[5]) if row[5] is not None else None,
                kickoff_local_text=str(row[6]) if row[6] is not None else None,
                kickoff_precision=str(row[7]),
                fixture_status=str(row[8]),
                source_round=str(row[9]) if row[9] is not None else None,
                observed_at_utc=str(row[10]),
            )
            for row in rows
        )

    def statistics(self, fixture_id: str) -> tuple[MatchStatisticRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT statistic_id, fixture_id, metric_key, team_role, phase,
                   evidence_class, evidence_state, value_integer, value_text,
                   unit, unknown_reason, source_assertion_id
            FROM match_statistics
            WHERE fixture_id = ?
            ORDER BY metric_key, team_role, phase, statistic_id
            """,
            (fixture_id,),
        ).fetchall()
        return tuple(
            MatchStatisticRecord(
                statistic_id=str(row[0]),
                fixture_id=str(row[1]),
                metric_key=str(row[2]),
                team_role=str(row[3]),
                phase=str(row[4]),
                evidence_class=str(row[5]),
                state=EvidenceState(str(row[6])),
                value_integer=int(row[7]) if row[7] is not None else None,
                value_text=str(row[8]) if row[8] is not None else None,
                unit=str(row[9]) if row[9] is not None else None,
                unknown_reason=str(row[10]) if row[10] is not None else None,
                source_assertion_id=str(row[11]),
            )
            for row in rows
        )

    def source_captures(self) -> tuple[SourceCaptureRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT c.capture_id, c.source_id, s.source_key, c.locator,
                   c.retrieved_at_utc, c.content_sha256, c.byte_length,
                   c.artifact_digest, s.allowed_use, c.retention_status,
                   s.redistributable, c.observed_terms, c.terms_reference
            FROM source_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            ORDER BY c.retrieved_at_utc, c.capture_id
            """
        ).fetchall()
        return tuple(
            SourceCaptureRecord(
                capture_id=str(row[0]),
                source_id=str(row[1]),
                source_key=str(row[2]),
                locator=str(row[3]),
                retrieved_at_utc=str(row[4]),
                content_sha256=str(row[5]),
                byte_length=int(row[6]),
                artifact_digest=str(row[7]),
                allowed_use=str(row[8]),
                retention_status=str(row[9]),
                redistributable=bool(row[10]),
                observed_terms=str(row[11]),
                terms_reference=str(row[12]),
            )
            for row in rows
        )

    def source_assertions(self) -> tuple[SourceAssertionRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT assertion_id, capture_id, source_row_key, subject_kind, subject_key,
                   evidence_type, predicate, raw_field_name, evidence_state,
                   raw_value_json, normalized_value_json, unknown_reason
            FROM source_assertions
            ORDER BY capture_id, source_row_key, predicate
            """
        ).fetchall()
        return tuple(
            SourceAssertionRecord(
                assertion_id=str(row[0]),
                capture_id=str(row[1]),
                source_row_key=str(row[2]),
                subject_kind=str(row[3]),
                subject_key=str(row[4]),
                evidence_type=str(row[5]),
                predicate=str(row[6]),
                raw_field_name=str(row[7]),
                evidence_state=EvidenceState(str(row[8])),
                raw_value_json=str(row[9]) if row[9] is not None else None,
                normalized_value_json=str(row[10]) if row[10] is not None else None,
                unknown_reason=str(row[11]) if row[11] is not None else None,
            )
            for row in rows
        )

    def conflicts(self, fixture_id: str) -> tuple[ConflictRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT conflict_id, subject_key, predicate, value_digest, status
            FROM conflict_sets
            WHERE subject_kind = 'FIXTURE' AND subject_key = ?
            ORDER BY predicate, conflict_id
            """,
            (fixture_id,),
        ).fetchall()
        result: list[ConflictRecord] = []
        for row in rows:
            members = connection.execute(
                """
                SELECT assertion_id FROM conflict_assertions
                WHERE conflict_id = ? ORDER BY assertion_id
                """,
                (str(row[0]),),
            ).fetchall()
            result.append(
                ConflictRecord(
                    conflict_id=str(row[0]),
                    subject_key=str(row[1]),
                    predicate=str(row[2]),
                    value_digest=str(row[3]),
                    status=str(row[4]),
                    assertion_ids=tuple(str(member[0]) for member in members),
                )
            )
        return tuple(result)

    def _existing_capture(
        self, source_id: str, cache_key: str, digest: str, retrieved_at_utc: str
    ) -> SourceCaptureRecord | None:
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT c.capture_id FROM source_captures AS c
            WHERE c.source_id = ? AND c.cache_key = ?
              AND c.content_sha256 = ? AND c.retrieved_at_utc = ?
            """,
            (source_id, cache_key, digest, retrieved_at_utc),
        ).fetchone()
        if row is None:
            return None
        return next(
            (capture for capture in self.source_captures() if capture.capture_id == str(row[0])),
            None,
        )

    def _ensure_source(
        self, tx: StoreTransaction, source_id: str, rights: _SourceRights, now: str
    ) -> None:
        tx.add_identifier_if_missing(CanonicalIdentifier("source", source_id))
        tx.execute(
            """
            INSERT INTO source_identities (
                source_id, source_key, canonical_name, owner, source_class,
                access_method, base_locator, allowed_use, retention_status,
                redistributable, terms_reference, terms_observed_at_utc, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO NOTHING
            """,
            (
                source_id,
                rights.source_key,
                rights.canonical_name,
                rights.owner,
                rights.source_class,
                rights.access_method,
                rights.base_locator,
                rights.allowed_use,
                rights.retention_status,
                int(rights.redistributable),
                rights.terms_reference,
                now,
                now,
            ),
        )

    def _ensure_origin(self, tx: StoreTransaction, origin_id: str, rights: _SourceRights) -> None:
        tx.add_identifier_if_missing(CanonicalIdentifier("origin", origin_id))
        tx.execute(
            """
            INSERT INTO independent_origins (
                origin_id, origin_key, organization, locator, classification, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(origin_id) DO NOTHING
            """,
            (
                origin_id,
                rights.source_key,
                rights.owner,
                rights.base_locator,
                "DATASET_ORIGIN",
                _utc_now_text(),
            ),
        )

    def _ensure_league(
        self, tx: StoreTransaction, league_id: str, league: LeagueConfig, now: str
    ) -> None:
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
                now,
            ),
        )

    def _ensure_season(
        self, tx: StoreTransaction, season_id: str, league_id: str, season: str, now: str
    ) -> None:
        tx.add_identifier_if_missing(CanonicalIdentifier("competition_season", season_id))
        tx.execute(
            """
            INSERT INTO competition_seasons (season_id, league_id, season_label, created_at_utc)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(season_id) DO NOTHING
            """,
            (season_id, league_id, season, now),
        )

    def _row_already_imported(
        self, tx: StoreTransaction, capture_id: str, source_row_key: str
    ) -> bool:
        row = tx.execute(
            "SELECT 1 FROM source_assertions WHERE capture_id = ? AND source_row_key = ? LIMIT 1",
            (capture_id, source_row_key),
        ).fetchone()
        return row is not None

    def _resolve_team(
        self,
        tx: StoreTransaction,
        league: LeagueConfig,
        source_name: str,
        source_id: str,
        league_id: str,
        captured_at: str,
    ) -> TeamResolution:
        resolution = self._teams.resolve(league, source_name)
        if resolution.state is MappingState.UNKNOWN:
            resolution = self._teams.resolve_or_register(league, source_name)
        if resolution.state is not MappingState.CONFIRMED:
            self._insert_source_team_mapping(
                tx, league, source_name, source_id, league_id, resolution, captured_at
            )
            return resolution
        assert resolution.canonical_team_id is not None
        canonical_name = resolution.canonical_name or source_name
        tx.add_identifier_if_missing(CanonicalIdentifier("team", resolution.canonical_team_id))
        tx.execute(
            """
            INSERT INTO teams (team_id, league_id, canonical_name, normalized_name, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(team_id) DO NOTHING
            """,
            (
                resolution.canonical_team_id,
                league_id,
                canonical_name,
                canonical_key(canonical_name),
                captured_at,
            ),
        )
        alias_id = deterministic_identifier(
            "team_alias",
            f"{league.key}:{resolution.canonical_team_id}:{canonical_key(source_name)}",
        )
        tx.add_identifier_if_missing(CanonicalIdentifier("team_alias", alias_id))
        tx.execute(
            """
            INSERT INTO team_aliases (
                alias_id, league_id, team_id, source_id, alias_name, normalized_alias,
                mapping_rule_version, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias_id) DO NOTHING
            """,
            (
                alias_id,
                league_id,
                resolution.canonical_team_id,
                source_id,
                source_name,
                canonical_key(source_name),
                "matchvet-t06-team-v1",
                captured_at,
            ),
        )
        self._insert_source_team_mapping(
            tx, league, source_name, source_id, league_id, resolution, captured_at
        )
        return resolution

    def _insert_source_team_mapping(
        self,
        tx: StoreTransaction,
        league: LeagueConfig,
        source_name: str,
        source_id: str,
        league_id: str,
        resolution: TeamResolution,
        captured_at: str,
    ) -> None:
        mapping_id = deterministic_identifier(
            "source_team_mapping", f"{source_id}:{league.key}:{canonical_key(source_name)}"
        )
        tx.add_identifier_if_missing(CanonicalIdentifier("source_team_mapping", mapping_id))
        tx.execute(
            """
            INSERT INTO source_team_mappings (
                mapping_id, source_id, league_id, source_team_key, source_team_name,
                mapping_state, team_id, candidates_json, mapping_rule_version, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mapping_id) DO NOTHING
            """,
            (
                mapping_id,
                source_id,
                league_id,
                canonical_key(source_name),
                source_name,
                resolution.state.value,
                resolution.canonical_team_id,
                _canonical_json(sorted(resolution.candidates)).decode("utf-8"),
                "matchvet-t06-team-v1",
                captured_at,
            ),
        )

    def _ensure_fixture(
        self,
        tx: StoreTransaction,
        fixture_id: str,
        identity_key: str,
        league_id: str,
        season_id: str,
        home: TeamResolution,
        away: TeamResolution,
        captured_at: str,
    ) -> None:
        assert home.canonical_team_id is not None
        assert away.canonical_team_id is not None
        tx.add_identifier_if_missing(CanonicalIdentifier("fixture", fixture_id))
        tx.execute(
            """
            INSERT INTO fixtures (
                fixture_id, league_id, season_id, home_team_id, away_team_id,
                identity_state, identity_key, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, 'CONFIRMED', ?, ?)
            ON CONFLICT(fixture_id) DO NOTHING
            """,
            (
                fixture_id,
                league_id,
                season_id,
                home.canonical_team_id,
                away.canonical_team_id,
                identity_key,
                captured_at,
            ),
        )

    def _import_row(
        self,
        tx: StoreTransaction,
        dataset: ParsedDataset,
        row: ParsedRow,
        capture_id: str,
        source_id: str,
        league_id: str,
        season_id: str,
        origin_id: str,
        captured_at: str,
        counters: dict[str, int],
    ) -> None:
        home = self._resolve_team(
            tx, dataset.league, row.home_team, source_id, league_id, captured_at
        )
        away = self._resolve_team(
            tx, dataset.league, row.away_team, source_id, league_id, captured_at
        )
        resolved = home.state is MappingState.CONFIRMED and away.state is MappingState.CONFIRMED
        if resolved:
            assert home.canonical_team_id is not None
            assert away.canonical_team_id is not None
            fixture_key = (
                f"{dataset.league.key}:{dataset.season}:"
                f"{home.canonical_team_id}:{away.canonical_team_id}"
            )
            fixture_id = deterministic_identifier("fixture", fixture_key)
            subject_kind = "FIXTURE"
            subject_key = fixture_id
            self._ensure_fixture(
                tx,
                fixture_id,
                fixture_key,
                league_id,
                season_id,
                home,
                away,
                captured_at,
            )
        else:
            fixture_id = None
            subject_kind = "UNRESOLVED_FIXTURE_ROW"
            subject_key = deterministic_identifier(
                "unresolved_fixture", f"{capture_id}:{row.source_row_key}"
            )
        assertions = self._insert_assertions(
            tx,
            dataset,
            row,
            capture_id,
            origin_id,
            subject_kind,
            subject_key,
            captured_at,
            counters,
        )
        if fixture_id is None:
            unresolved_id = subject_key
            tx.add_identifier_if_missing(CanonicalIdentifier("unresolved_fixture", unresolved_id))
            candidates = sorted(set(home.candidates + away.candidates))
            tx.execute(
                """
                INSERT INTO unresolved_fixture_rows (
                    unresolved_id, capture_id, source_row_key, league_id, season_id,
                    home_name, away_name, resolution_state, candidates_json, reason, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unresolved_id) DO NOTHING
                """,
                (
                    unresolved_id,
                    capture_id,
                    row.source_row_key,
                    league_id,
                    season_id,
                    row.home_team,
                    row.away_team,
                    "AMBIGUOUS"
                    if MappingState.AMBIGUOUS in (home.state, away.state)
                    else "UNKNOWN",
                    _canonical_json(candidates).decode("utf-8"),
                    "TEAM_MAPPING_UNRESOLVED",
                    captured_at,
                ),
            )
            counters["unresolved_rows"] += 1
            return
        revision_assertions = [
            assertions["kickoff"],
            assertions["home_team"],
            assertions["away_team"],
        ]
        fixture_status = _fixture_status(row)
        revision_payload = {
            "fixture_status": fixture_status,
            "kickoff_local_text": row.kickoff_local_text,
            "kickoff_precision": row.kickoff_precision,
            "kickoff_state": (
                EvidenceState.OBSERVED.value
                if row.kickoff_local_date is not None
                else EvidenceState.UNKNOWN.value
            ),
            "kickoff_utc": row.kickoff_utc.isoformat() if row.kickoff_utc else None,
            "source_round": row.source_round,
        }
        revision_digest = sha256_bytes(_canonical_json(revision_payload))
        revision_id = deterministic_identifier(
            "fixture_revision", f"{fixture_id}:{revision_digest}"
        )
        predecessor = tx.execute(
            """
            SELECT revision_id FROM fixture_revisions
            WHERE fixture_id = ? ORDER BY observed_at_utc DESC, revision_id DESC LIMIT 1
            """,
            (fixture_id,),
        ).fetchone()
        existing_revision = tx.execute(
            """
            SELECT revision_id FROM fixture_revisions
            WHERE fixture_id = ? AND revision_digest = ?
            """,
            (fixture_id, revision_digest),
        ).fetchone()
        if existing_revision is None:
            tx.add_identifier_if_missing(CanonicalIdentifier("fixture_revision", revision_id))
            tx.execute(
                """
                INSERT INTO fixture_revisions (
                    revision_id, fixture_id, predecessor_revision_id, revision_digest,
                    kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
                    fixture_status, source_round, observed_at_utc, source_capture_id,
                    source_assertion_ids_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    fixture_id,
                    str(predecessor[0]) if predecessor is not None else None,
                    revision_digest,
                    revision_payload["kickoff_state"],
                    revision_payload["kickoff_utc"],
                    row.kickoff_local_text,
                    row.kickoff_precision,
                    fixture_status,
                    row.source_round,
                    captured_at,
                    capture_id,
                    _canonical_json(sorted(revision_assertions)).decode("utf-8"),
                    captured_at,
                ),
            )
            counters["revisions_appended"] += 1
        else:
            revision_id = str(existing_revision[0])
        for assertion_id in revision_assertions:
            tx.execute(
                """
                INSERT INTO fixture_revision_assertions (revision_id, assertion_id)
                VALUES (?, ?) ON CONFLICT(revision_id, assertion_id) DO NOTHING
                """,
                (revision_id, assertion_id),
            )
        for metric_key, parsed in row.fields.items():
            role, phase, unit = _FIELD_META[metric_key]
            assertion_id = assertions[metric_key]
            integer_value = (
                parsed.value
                if isinstance(parsed.value, int) and not isinstance(parsed.value, bool)
                else None
            )
            text_value = parsed.value if isinstance(parsed.value, str) else None
            statistic_id = deterministic_identifier(
                "match_statistic", f"{fixture_id}:{assertion_id}:{metric_key}:{role}:{phase}"
            )
            tx.add_identifier_if_missing(CanonicalIdentifier("match_statistic", statistic_id))
            tx.execute(
                """
                INSERT INTO match_statistics (
                    statistic_id, fixture_id, season_id, metric_key, team_role, phase,
                    evidence_class, evidence_state, value_integer, value_text, unit,
                    unknown_reason, source_assertion_id, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(statistic_id) DO NOTHING
                """,
                (
                    statistic_id,
                    fixture_id,
                    season_id,
                    metric_key,
                    role,
                    phase,
                    parsed.evidence_class,
                    parsed.state.value,
                    integer_value,
                    text_value,
                    unit,
                    parsed.unknown_reason,
                    assertion_id,
                    captured_at,
                ),
            )
            counters["statistics_imported"] += 1
            if parsed.state is UNKNOWN:
                counters["unknown_fields"] += 1
            self._record_conflict(tx, "FIXTURE", fixture_id, metric_key, assertion_id)
        self._record_conflict(tx, "FIXTURE", fixture_id, "kickoff", assertions["kickoff"])
        counters["fixtures_imported"] += 1

    def _insert_assertions(
        self,
        tx: StoreTransaction,
        dataset: ParsedDataset,
        row: ParsedRow,
        capture_id: str,
        origin_id: str,
        subject_kind: str,
        subject_key: str,
        captured_at: str,
        counters: dict[str, int],
    ) -> dict[str, str]:
        kickoff_state = OBSERVED if row.kickoff_local_date is not None else UNKNOWN
        kickoff_value: str | None = None
        if row.kickoff_utc is not None:
            kickoff_value = row.kickoff_utc.isoformat()
        elif row.kickoff_local_date is not None:
            kickoff_value = row.kickoff_local_date.isoformat()
        fields: dict[str, tuple[ParsedField, str, str]] = {
            "home_team": (
                ParsedField("home_team", OBSERVED, row.home_team),
                "HomeTeam" if dataset.source_kind is SourceKind.FOOTBALL_DATA else "team1",
                row.home_team,
            ),
            "away_team": (
                ParsedField("away_team", OBSERVED, row.away_team),
                "AwayTeam" if dataset.source_kind is SourceKind.FOOTBALL_DATA else "team2",
                row.away_team,
            ),
            "kickoff": (
                ParsedField(
                    "kickoff",
                    kickoff_state,
                    kickoff_value,
                    unknown_reason="SOURCE_MISSING_FIELD" if kickoff_state is UNKNOWN else None,
                ),
                "Date/Time",
                _raw_kickoff(row),
            ),
        }
        for metric_key, parsed in row.fields.items():
            fields[metric_key] = (
                parsed,
                _RAW_FIELD_NAMES.get(metric_key, metric_key),
                parsed.raw_value or "",
            )
        assertion_ids: dict[str, str] = {}
        for predicate, (parsed, raw_field_name, raw_value) in fields.items():
            assertion_id = deterministic_identifier(
                "source_assertion", f"{capture_id}:{row.source_row_key}:{predicate}"
            )
            assertion_ids[predicate] = assertion_id
            tx.add_identifier_if_missing(CanonicalIdentifier("source_assertion", assertion_id))
            raw_json = _optional_json(raw_value) if raw_value else None
            normalized_json = _optional_json(parsed.value)
            evidence_type = (
                "FIXTURE"
                if predicate in {"home_team", "away_team", "kickoff"}
                else (
                    "OPTIONAL_EVIDENCE"
                    if parsed.evidence_class == "OPTIONAL_EVIDENCE"
                    else "MATCH_STATISTIC"
                )
            )
            tx.execute(
                """
                INSERT INTO source_assertions (
                    assertion_id, capture_id, origin_id, source_row_key,
                    subject_kind, subject_key, evidence_type, predicate,
                    raw_field_name, raw_value_json, normalized_value_json,
                    evidence_state, unknown_reason, event_time_utc, effective_time_utc,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assertion_id) DO NOTHING
                """,
                (
                    assertion_id,
                    capture_id,
                    origin_id,
                    row.source_row_key,
                    subject_kind,
                    subject_key,
                    evidence_type,
                    predicate,
                    raw_field_name,
                    raw_json,
                    normalized_json,
                    parsed.state.value,
                    parsed.unknown_reason,
                    kickoff_value if predicate == "kickoff" else None,
                    kickoff_value if predicate == "kickoff" else None,
                    captured_at,
                ),
            )
            if parsed.state is UNKNOWN:
                counters["unknown_fields"] += 1
        return assertion_ids

    def _record_conflict(
        self,
        tx: StoreTransaction,
        subject_kind: str,
        subject_key: str,
        predicate: str,
        assertion_id: str,
    ) -> None:
        del assertion_id
        rows = tx.execute(
            """
            SELECT assertion_id, normalized_value_json
            FROM source_assertions
            WHERE subject_kind = ? AND subject_key = ? AND predicate = ?
              AND evidence_state = 'OBSERVED' AND normalized_value_json IS NOT NULL
            ORDER BY assertion_id
            """,
            (subject_kind, subject_key, predicate),
        ).fetchall()
        values = sorted({str(row[1]) for row in rows})
        if len(values) < 2:
            return
        value_digest = sha256_bytes(_canonical_json(values))
        conflict_id = deterministic_identifier(
            "conflict_set", f"{subject_kind}:{subject_key}:{predicate}:{value_digest}"
        )
        tx.add_identifier_if_missing(CanonicalIdentifier("conflict_set", conflict_id))
        tx.execute(
            """
            INSERT INTO conflict_sets (
                conflict_id, subject_kind, subject_key, predicate,
                value_digest, status, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, 'UNRESOLVED', ?)
            ON CONFLICT(conflict_id) DO NOTHING
            """,
            (
                conflict_id,
                subject_kind,
                subject_key,
                predicate,
                value_digest,
                _utc_now_text(),
            ),
        )
        for row in rows:
            tx.execute(
                """
                INSERT INTO conflict_assertions (conflict_id, assertion_id)
                VALUES (?, ?) ON CONFLICT(conflict_id, assertion_id) DO NOTHING
                """,
                (conflict_id, str(row[0])),
            )

    def _count_conflicts_for_dataset(
        self, dataset: ParsedDataset, league_id: str, season_id: str
    ) -> int:
        del dataset
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT count(*)
            FROM conflict_sets AS c
            JOIN fixtures AS f ON f.fixture_id = c.subject_key
            WHERE c.subject_kind = 'FIXTURE' AND f.league_id = ? AND f.season_id = ?
            """,
            (league_id, season_id),
        ).fetchone()
        return int(row[0]) if row is not None else 0


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Timestamps must be ISO-8601 values with a UTC offset.") from error
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat()


def _optional_utc(value: str | None) -> str | None:
    return _canonical_utc(value) if value is not None else None


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _optional_json(value: object) -> str | None:
    return _canonical_json(value).decode("utf-8") if value is not None else None


def _raw_kickoff(row: ParsedRow) -> str:
    if row.kickoff_local_text is not None:
        return row.kickoff_local_text
    if row.kickoff_local_date is not None:
        return row.kickoff_local_date.isoformat()
    return ""


def _fixture_status(row: ParsedRow) -> str:
    home = row.fields["full_time_home_goals"]
    away = row.fields["full_time_away_goals"]
    if home.state is OBSERVED and away.state is OBSERVED:
        return "COMPLETED"
    if row.kickoff_local_date is not None:
        return "SCHEDULED"
    return "UNKNOWN"


@dataclass(frozen=True)
class DownloadedSource:
    content: bytes
    retrieved_at_utc: str
    response_status: int
    content_type: str
    from_cache: bool
    bytes_downloaded: int


class SourceFetcher(Protocol):
    def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource: ...


class StaticSourceFetcher:
    """Deterministic fetcher for offline tests and recorded source examples."""

    def __init__(
        self,
        sources: Mapping[str, bytes],
        *,
        retrieved_at_utc: str = "2026-09-13T12:00:00+00:00",
        content_type: str = "application/octet-stream",
    ) -> None:
        self.sources = dict(sources)
        self.retrieved_at_utc = retrieved_at_utc
        self.content_type = content_type
        self.calls: list[str] = []

    def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource:
        del cache_key, refresh
        self.calls.append(url)
        try:
            content = self.sources[url]
        except KeyError as error:
            raise SourceUnavailable(f"No recorded source fixture exists for {url}.") from error
        return DownloadedSource(
            content=content,
            retrieved_at_utc=self.retrieved_at_utc,
            response_status=200,
            content_type=self.content_type,
            from_cache=False,
            bytes_downloaded=len(content),
        )


class ResumableSourceDownloader:
    """Download only approved direct sources with private cache and range resume."""

    _ALLOWED_HOSTS = frozenset(
        {"www.football-data.co.uk", "football-data.co.uk", "raw.githubusercontent.com"}
    )

    def __init__(
        self,
        private_root: Path,
        *,
        max_source_bytes: int = 32 * 1024 * 1024,
        network_cap_bytes: int | None = None,
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: int = 6 * 60 * 60,
        cache_storage_cap_bytes: int = SETTLED_RESOURCE_BUDGET.managed_storage_cap_bytes,
    ) -> None:
        selected_network_cap = network_cap_bytes or SETTLED_RESOURCE_BUDGET.routine_network_bytes
        if (
            min(max_source_bytes, selected_network_cap, cache_ttl_seconds, cache_storage_cap_bytes)
            <= 0
        ):
            raise ValueError("Downloader limits must be positive.")
        self.private_root = private_root.resolve()
        self.cache_root = self.private_root / "cache" / "t06"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cache_root, 0o700)
        self.max_source_bytes = max_source_bytes
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_storage_cap_bytes = cache_storage_cap_bytes
        self.network_cap_bytes = selected_network_cap
        self._network_cap_explicit = network_cap_bytes is not None
        self.timeout_seconds = timeout_seconds
        self.network_bytes = 0

    def configure_for_plan(self, *, historical: bool) -> None:
        if self._network_cap_explicit:
            return
        self.network_cap_bytes = (
            SETTLED_RESOURCE_BUDGET.historical_network_bytes
            if historical
            else SETTLED_RESOURCE_BUDGET.routine_network_bytes
        )

    def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource:
        self._validate_url(url)
        cache_stem = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        data_path = self.cache_root / f"{cache_stem}.data"
        meta_path = self.cache_root / f"{cache_stem}.json"
        cached = self._read_cached(data_path, meta_path, refresh)
        if cached is not None:
            return cached
        part_path = self.cache_root / f"{cache_stem}.part"
        offset = part_path.stat().st_size if part_path.exists() else 0
        headers = {"User-Agent": "MatchVet-T06/1.0", "Accept": "text/csv,application/json"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = Request(url, headers=headers, method="GET")
        try:
            response = urlopen(request, timeout=self.timeout_seconds)
        except (HTTPError, URLError, OSError) as error:
            raise SourceUnavailable(
                f"Approved source retrieval failed for {url}: {error}"
            ) from error
        try:
            geturl = getattr(response, "geturl", None)
            final_url = str(geturl()) if callable(geturl) else url
            self._validate_url(final_url)
        except Exception:
            response.close()
            raise
        status = int(getattr(response, "status", response.getcode()))
        content_type = str(response.headers.get("Content-Type", "application/octet-stream")).split(
            ";", maxsplit=1
        )[0]
        if status not in {200, 206}:
            response.close()
            raise SourceUnavailable(f"Approved source returned HTTP {status} for {url}.")
        append = offset > 0 and status == 206
        bytes_downloaded = 0
        cache_bytes = self._cache_size() - (offset if not append else 0)
        try:
            mode = "ab" if append else "wb"
            with part_path.open(mode) as target:
                os.chmod(part_path, 0o600)
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    bytes_downloaded += len(chunk)
                    if bytes_downloaded + (offset if append else 0) > self.max_source_bytes:
                        raise SourceUnavailable(
                            f"Source exceeded the {self.max_source_bytes}-byte limit."
                        )
                    if self.network_bytes + bytes_downloaded > self.network_cap_bytes:
                        raise SourceUnavailable(
                            "Historical download session exceeded its network cap."
                        )
                    if cache_bytes + len(chunk) > self.cache_storage_cap_bytes:
                        raise SourceUnavailable(
                            "Private T06 cache would exceed its managed-storage budget."
                        )
                    target.write(chunk)
                    cache_bytes += len(chunk)
                target.flush()
                os.fsync(target.fileno())
        except OSError, SourceUnavailable:
            response.close()
            raise
        finally:
            response.close()
        self.network_bytes += bytes_downloaded
        os.replace(part_path, data_path)
        content = data_path.read_bytes()
        retrieved_at = _utc_now_text()
        metadata = {
            "content_sha256": sha256_bytes(content),
            "content_type": content_type,
            "retrieved_at_utc": retrieved_at,
            "response_status": status,
            "url": url,
        }
        meta_tmp = meta_path.with_suffix(".tmp")
        meta_tmp.write_text(_canonical_json(metadata).decode("utf-8"), encoding="utf-8")
        os.chmod(meta_tmp, 0o600)
        descriptor = os.open(meta_tmp, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(meta_tmp, meta_path)
        return DownloadedSource(
            content, retrieved_at, status, content_type, False, bytes_downloaded
        )

    def _cache_size(self) -> int:
        try:
            return sum(path.stat().st_size for path in self.cache_root.iterdir() if path.is_file())
        except OSError:
            return self.cache_storage_cap_bytes

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self._ALLOWED_HOSTS:
            raise SourcePolicyError("T06 permits only approved HTTPS source hosts.")

    def _read_cached(
        self, data_path: Path, meta_path: Path, refresh: bool
    ) -> DownloadedSource | None:
        if refresh or not data_path.is_file() or not meta_path.is_file():
            return None
        try:
            raw: object = json.loads(meta_path.read_text(encoding="utf-8"))
            content = data_path.read_bytes()
            if not isinstance(raw, dict):
                return None
            retrieved = raw.get("retrieved_at_utc")
            digest = raw.get("content_sha256")
            if not isinstance(retrieved, str) or not isinstance(digest, str):
                return None
            age = datetime.now(UTC) - datetime.fromisoformat(retrieved)
            if age.total_seconds() > self.cache_ttl_seconds:
                return None
            if digest != sha256_bytes(content):
                return None
            return DownloadedSource(
                content,
                retrieved,
                int(raw.get("response_status", 200)),
                str(raw.get("content_type", "application/octet-stream")),
                True,
                0,
            )
        except OSError, ValueError, TypeError:
            return None


@dataclass(frozen=True)
class IngestionPlan:
    current_season: str
    historical_seasons: tuple[str, ...] = ()
    leagues: tuple[LeagueConfig, ...] = TARGET_LEAGUES
    use_openfootball_fallback: bool = True
    refresh_current: bool = False

    def __post_init__(self) -> None:
        season_code(self.current_season)
        for season in self.historical_seasons:
            season_code(season)
        if len({league.key for league in self.leagues}) != len(self.leagues):
            raise ValueError("Ingestion plan league membership must be unique.")
        if any(league.key not in _LEAGUES_BY_KEY for league in self.leagues):
            raise ValueError(
                "Ingestion plan contains a league outside the configured Target League Set."
            )

    @property
    def seasons(self) -> tuple[str, ...]:
        return (self.current_season, *self.historical_seasons)

    @property
    def plan_digest(self) -> str:
        return sha256_bytes(
            _canonical_json(
                {
                    "current_season": self.current_season,
                    "historical_seasons": self.historical_seasons,
                    "leagues": [league.key for league in self.leagues],
                    "source_policy": "t06-source-policy-v1",
                    "use_openfootball_fallback": self.use_openfootball_fallback,
                }
            )
        )

    @property
    def run_key(self) -> str:
        return f"t06-fixture-history:{self.plan_digest}"

    @property
    def expected_network_bytes(self) -> int:
        return max(1, len(self.seasons) * len(self.leagues) * 2 * 1024 * 1024)


@dataclass(frozen=True)
class AcquisitionIssue:
    source_kind: SourceKind
    league_key: str
    season: str
    url: str
    reason: str
    fallback_attempted: bool


@dataclass(frozen=True)
class AcquisitionReport:
    plan_digest: str
    imports: tuple[ImportResult, ...]
    issues: tuple[AcquisitionIssue, ...]
    bytes_downloaded: int
    cache_hits: int
    fallback_imports: int

    @property
    def source_capture_ids(self) -> tuple[str, ...]:
        return tuple(item.source_capture_id for item in self.imports)

    @property
    def digest(self) -> str:
        return sha256_bytes(
            _canonical_json(
                {
                    "bytes_downloaded": self.bytes_downloaded,
                    "cache_hits": self.cache_hits,
                    "fallback_imports": self.fallback_imports,
                    "imports": [
                        {
                            "capture_id": item.source_capture_id,
                            "digest": item.source_digest,
                            "league": item.league_key,
                            "season": item.season,
                        }
                        for item in self.imports
                    ],
                    "issues": [
                        {
                            "league": issue.league_key,
                            "reason": issue.reason,
                            "season": issue.season,
                            "source": issue.source_kind.value,
                            "url": issue.url,
                        }
                        for issue in self.issues
                    ],
                    "plan_digest": self.plan_digest,
                }
            )
        )


class FixtureHistoryAcquirer:
    """Acquire primary files and permitted fallback files for an IngestionPlan."""

    def __init__(
        self,
        importer: FixtureHistoryImporter,
        fetcher: SourceFetcher,
    ) -> None:
        self.importer = importer
        self.fetcher = fetcher
        self.football_data_parser = FootballDataCSVParser()
        self.openfootball_parser = OpenFootballJSONParser()

    def acquire(self, plan: IngestionPlan) -> AcquisitionReport:
        configure = getattr(self.fetcher, "configure_for_plan", None)
        if callable(configure):
            configure(historical=bool(plan.historical_seasons))
        imports: list[ImportResult] = []
        issues: list[AcquisitionIssue] = []
        bytes_downloaded = 0
        cache_hits = 0
        fallback_imports = 0
        for season in plan.seasons:
            for league in plan.leagues:
                primary_url = football_data_url(league, season)
                refresh = plan.refresh_current and season == plan.current_season
                try:
                    downloaded = self.fetcher.fetch(
                        primary_url,
                        cache_key=f"football-data:{league.key}:{season}",
                        refresh=refresh,
                    )
                except SourceUnavailable as primary_error:
                    if not plan.use_openfootball_fallback or not league.openfootball_supported:
                        issues.append(
                            AcquisitionIssue(
                                SourceKind.FOOTBALL_DATA,
                                league.key,
                                season,
                                primary_url,
                                str(primary_error),
                                False,
                            )
                        )
                        continue
                    fallback_url = openfootball_url(league, season)
                    try:
                        downloaded = self.fetcher.fetch(
                            fallback_url,
                            cache_key=f"openfootball:{league.key}:{season}",
                            refresh=refresh,
                        )
                    except SourceUnavailable as fallback_error:
                        issues.append(
                            AcquisitionIssue(
                                SourceKind.OPENFOOTBALL,
                                league.key,
                                season,
                                fallback_url,
                                str(fallback_error),
                                True,
                            )
                        )
                        continue
                    dataset = self.openfootball_parser.parse(
                        downloaded.content, league=league, season=season
                    )
                    result = self.importer.import_dataset(
                        dataset,
                        downloaded.content,
                        SourceCaptureInput(
                            source_url=fallback_url,
                            retrieved_at_utc=downloaded.retrieved_at_utc,
                            response_status=downloaded.response_status,
                            content_type=downloaded.content_type,
                            observed_terms="OpenFootball CC0",
                            cache_key=f"openfootball:{league.key}:{season}",
                        ),
                    )
                    imports.append(result)
                    fallback_imports += 1
                    bytes_downloaded += downloaded.bytes_downloaded
                    cache_hits += int(downloaded.from_cache)
                    continue
                dataset = self.football_data_parser.parse(
                    downloaded.content, league=league, season=season
                )
                result = self.importer.import_dataset(
                    dataset,
                    downloaded.content,
                    SourceCaptureInput(
                        source_url=primary_url,
                        retrieved_at_utc=downloaded.retrieved_at_utc,
                        response_status=downloaded.response_status,
                        content_type=downloaded.content_type,
                        observed_terms=(
                            "Football-Data.co.uk restricted private local noncommercial use"
                        ),
                        cache_key=f"football-data:{league.key}:{season}",
                    ),
                )
                imports.append(result)
                bytes_downloaded += downloaded.bytes_downloaded
                cache_hits += int(downloaded.from_cache)
        return AcquisitionReport(
            plan.plan_digest,
            tuple(imports),
            tuple(issues),
            bytes_downloaded,
            cache_hits,
            fallback_imports,
        )


def build_t06_input_contract(plan: IngestionPlan) -> RunInputContract:
    schema_identity = ":".join(migration.checksum for migration in MIGRATIONS)
    environment_identity = _canonical_json(
        {
            "machine": platform.machine(),
            "platform": sys.platform,
            "python": platform.python_version(),
        }
    ).decode("utf-8")
    return RunInputContract.from_values(
        {
            "source": f"T06:SOURCE_PLAN:{plan.plan_digest}",
            "cutoff": "T06:NO_MATCHWEEK_CUTOFF",
            "preference_set": "T06:NOT_APPLICABLE",
            "policy": "T06:NOT_APPLICABLE",
            "model": "T06:NOT_APPLICABLE",
            "feature": "T06:RAW_STRUCTURED_FIELDS_ONLY",
            "research_rule": "T06:SOURCE_POLICY_V1",
            "canonical_contract": "MATCHVET_CANONICAL_CONTRACT_V1",
            "schema": schema_identity,
            "environment": environment_identity,
            "software": "MATCHVET_T06_INGESTION_V1",
        }
    )


class T06AcquisitionRunner:
    """Run source downloads/imports inside T04's durable checkpoint lifecycle."""

    def __init__(
        self,
        store: Store,
        acquirer: FixtureHistoryAcquirer,
        *,
        budget: ResourceBudget | None = None,
    ) -> None:
        self.store = store
        self.acquirer = acquirer
        self._budget = budget or SETTLED_RESOURCE_BUDGET
        self.last_report: AcquisitionReport | None = None

    def start(
        self,
        plan: IngestionPlan,
        *,
        observation: ResourceObservation,
        progress: Callable[[RunStatus], None] | None = None,
    ) -> RunStatus:
        coordinator = RunCoordinator(self.store, budget=self._budget_for_plan(plan))
        return coordinator.start(
            matchweek=plan.run_key,
            inputs=build_t06_input_contract(plan),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda context: self._execute(plan, context),
            progress=progress,
        )

    def resume(
        self,
        run_id: str,
        plan: IngestionPlan,
        *,
        observation: ResourceObservation,
        progress: Callable[[RunStatus], None] | None = None,
    ) -> RunStatus:
        coordinator = RunCoordinator(self.store, budget=self._budget_for_plan(plan))
        return coordinator.resume(
            run_id,
            inputs=build_t06_input_contract(plan),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda context: self._execute(plan, context),
            progress=progress,
        )

    def _estimate(self, plan: IngestionPlan) -> ResourceEstimate:
        budget = self._budget_for_plan(plan)
        return ResourceEstimate(
            storage_growth_bytes=min(plan.expected_network_bytes + 4 * MIB, 512 * MIB),
            peak_memory_bytes=256 * MIB,
            duration_seconds=min(7_200, max(60, len(plan.seasons) * len(plan.leagues) * 30)),
            network_bytes=min(plan.expected_network_bytes, budget.routine_network_bytes),
            cpu_heavy_operations=1,
        )

    def _budget_for_plan(self, plan: IngestionPlan) -> ResourceBudget:
        if not plan.historical_seasons:
            return self._budget
        return replace(
            self._budget,
            routine_network_bytes=self._budget.historical_network_bytes,
        )

    def _execute(self, plan: IngestionPlan, context: WorkContext) -> WorkResult:
        if context.phase is not RunPhase.EVIDENCE_ACQUISITION:
            return WorkResult.for_phase(context.phase)
        report = self.acquirer.acquire(plan)
        self.last_report = report
        payload = _canonical_json(
            {
                "bytes_downloaded": report.bytes_downloaded,
                "cache_hits": report.cache_hits,
                "fallback_imports": report.fallback_imports,
                "imports": [
                    {
                        "capture_id": item.source_capture_id,
                        "digest": item.source_digest,
                        "league": item.league_key,
                        "season": item.season,
                    }
                    for item in report.imports
                ],
                "issues": [
                    {
                        "fallback_attempted": issue.fallback_attempted,
                        "league": issue.league_key,
                        "reason": issue.reason,
                        "season": issue.season,
                        "source": issue.source_kind.value,
                        "url": issue.url,
                    }
                    for issue in report.issues
                ],
                "plan_digest": report.plan_digest,
                "report_digest": report.digest,
                "schema_version": 1,
            }
        )
        artifact = ArtifactStore(self.store).publish_artifact(
            payload,
            "application/vnd.matchvet.t06-acquisition+json",
            retention_class="REUSABLE",
        )
        return WorkResult(result_digest=report.digest, artifact_digests=(artifact.digest,))

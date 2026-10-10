"""T06 fixture and structured match-history acquisition.

This module deliberately stops at source-backed facts. It does not freeze a
Matchweek, research contextual evidence, or calculate a prediction.
"""

from __future__ import annotations

import contextlib
import csv
import email.utils
import errno
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import platform
import queue
import re
import socket
import sqlite3
import ssl
import sys
import threading
import time as time_module
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit
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

if TYPE_CHECKING:
    from matchvet.fixture_coverage import (
        FixtureCoverageAssessment,
        ProviderAttempt,
        ProviderAttemptState,
    )
    from matchvet.pro_league_team_alias_registry import (
        ApprovedProLeagueAlias,
        ProLeagueTeamAliasRegistry,
    )
    from matchvet.team_alias_registry import ApprovedAlias, TeamAliasRegistry


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
    OPENFOOTBALL_TEXT = "OPENFOOTBALL_TEXT"
    OPERATOR_OFFICIAL_FIXTURE_OBSERVATION = "OPERATOR_OFFICIAL_FIXTURE_OBSERVATION"
    OPERATOR_OFFICIAL_FIXTURE_OBSERVATION_V2 = "OPERATOR_OFFICIAL_FIXTURE_OBSERVATION_V2"


class MappingState(StrEnum):
    CONFIRMED = "CONFIRMED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class TeamIdentityPolicy(StrEnum):
    REGISTER_UNKNOWN = "REGISTER_UNKNOWN"
    KNOWN_ONLY = "KNOWN_ONLY"


class IngestionError(Exception):
    """Base class for bounded T06 acquisition failures."""


@dataclass(frozen=True)
class SourceTransportAttempt:
    number: int
    url: str
    started_at_utc: str
    completed_at_utc: str
    elapsed_seconds: float
    response_status: int | None
    classification: str
    bytes_received: int
    response_digest: str | None = None
    retry_after_seconds: float | None = None
    retry_delay_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "url": self.url,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "elapsed_seconds": self.elapsed_seconds,
            "response_status": self.response_status,
            "classification": self.classification,
            "bytes_received": self.bytes_received,
            "response_digest": self.response_digest,
            "retry_after_seconds": self.retry_after_seconds,
            "retry_delay_seconds": self.retry_delay_seconds,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceTransportAttempt:
        if not isinstance(value, dict):
            raise SourceIntegrityError("Retained transport attempt is not an object.")
        fields = {
            "number",
            "url",
            "started_at_utc",
            "completed_at_utc",
            "elapsed_seconds",
            "response_status",
            "classification",
            "bytes_received",
            "response_digest",
            "retry_after_seconds",
            "retry_delay_seconds",
        }
        if set(value) != fields:
            raise SourceIntegrityError("Retained transport attempt has an unsupported shape.")
        if (
            type(value["number"]) is not int
            or type(value["bytes_received"]) is not int
            or not isinstance(value["url"], str)
            or not isinstance(value["started_at_utc"], str)
            or not isinstance(value["completed_at_utc"], str)
            or not isinstance(value["classification"], str)
            or not isinstance(value["elapsed_seconds"], (int, float))
            or (value["response_status"] is not None and type(value["response_status"]) is not int)
            or (
                value["response_digest"] is not None
                and not isinstance(value["response_digest"], str)
            )
        ):
            raise SourceIntegrityError("Retained transport attempt has invalid field values.")
        return cls(
            value["number"],
            value["url"],
            value["started_at_utc"],
            value["completed_at_utc"],
            float(value["elapsed_seconds"]),
            value["response_status"],
            value["classification"],
            value["bytes_received"],
            value["response_digest"],
            _optional_float(value["retry_after_seconds"]),
            _optional_float(value["retry_delay_seconds"]),
        )


@dataclass(frozen=True)
class SourceRedirect:
    from_url: str
    to_url: str
    response_status: int
    validated: bool
    refusal_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "from_url": self.from_url,
            "to_url": self.to_url,
            "response_status": self.response_status,
            "validated": self.validated,
            "refusal_reason": self.refusal_reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceRedirect:
        if (
            not isinstance(value, dict)
            or set(value)
            != {"from_url", "to_url", "response_status", "validated", "refusal_reason"}
            or not isinstance(value.get("from_url"), str)
            or not isinstance(value.get("to_url"), str)
            or type(value.get("response_status")) is not int
            or not isinstance(value.get("validated"), bool)
            or (
                value.get("refusal_reason") is not None
                and not isinstance(value.get("refusal_reason"), str)
            )
        ):
            raise SourceIntegrityError("Retained transport redirect has an unsupported shape.")
        return cls(
            value["from_url"],
            value["to_url"],
            value["response_status"],
            value["validated"],
            value["refusal_reason"],
        )


@dataclass(frozen=True)
class SourceTransportProvenance:
    requested_url: str
    final_url: str | None
    redirects: tuple[SourceRedirect, ...]
    retrieved_at_utc: str | None
    response_status: int | None
    response_digest: str | None
    content_digest: str | None
    content_byte_count: int
    network_byte_count: int
    request_count: int
    failure_classification: str | None
    retry_count: int
    elapsed_seconds: float
    attempts: tuple[SourceTransportAttempt, ...]

    @property
    def redirect_chain(self) -> tuple[str, ...]:
        return tuple(hop.to_url for hop in self.redirects)

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "redirects": [hop.to_dict() for hop in self.redirects],
            "retrieved_at_utc": self.retrieved_at_utc,
            "response_status": self.response_status,
            "response_digest": self.response_digest,
            "content_digest": self.content_digest,
            "content_byte_count": self.content_byte_count,
            "network_byte_count": self.network_byte_count,
            "request_count": self.request_count,
            "failure_classification": self.failure_classification,
            "retry_count": self.retry_count,
            "elapsed_seconds": self.elapsed_seconds,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceTransportProvenance:
        fields = {
            "requested_url",
            "final_url",
            "redirects",
            "retrieved_at_utc",
            "response_status",
            "response_digest",
            "content_digest",
            "content_byte_count",
            "network_byte_count",
            "request_count",
            "failure_classification",
            "retry_count",
            "elapsed_seconds",
            "attempts",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise SourceIntegrityError("Retained transport provenance has an unsupported shape.")
        if (
            not isinstance(value.get("requested_url"), str)
            or (value.get("final_url") is not None and not isinstance(value.get("final_url"), str))
            or (
                value.get("retrieved_at_utc") is not None
                and not isinstance(value.get("retrieved_at_utc"), str)
            )
            or (
                value.get("response_status") is not None
                and type(value.get("response_status")) is not int
            )
            or (
                value.get("response_digest") is not None
                and not isinstance(value.get("response_digest"), str)
            )
            or (
                value.get("content_digest") is not None
                and not isinstance(value.get("content_digest"), str)
            )
            or type(value.get("content_byte_count")) is not int
            or type(value.get("network_byte_count")) is not int
            or type(value.get("request_count")) is not int
            or (
                value.get("failure_classification") is not None
                and not isinstance(value.get("failure_classification"), str)
            )
            or type(value.get("retry_count")) is not int
            or not isinstance(value.get("elapsed_seconds"), (int, float))
            or not isinstance(value.get("redirects"), list)
            or not isinstance(value.get("attempts"), list)
        ):
            raise SourceIntegrityError("Retained transport provenance has invalid field values.")
        return cls(
            value["requested_url"],
            value["final_url"],
            tuple(SourceRedirect.from_dict(item) for item in value["redirects"]),
            value["retrieved_at_utc"],
            value["response_status"],
            value["response_digest"],
            value["content_digest"],
            value["content_byte_count"],
            value["network_byte_count"],
            value["request_count"],
            value["failure_classification"],
            value["retry_count"],
            float(value["elapsed_seconds"]),
            tuple(SourceTransportAttempt.from_dict(item) for item in value["attempts"]),
        )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SourceIntegrityError("Retained transport timing is invalid.")
    return float(value)


class SourceParseError(IngestionError):
    """The source document cannot be structurally parsed."""


class SourcePolicyError(IngestionError):
    """The requested source or field is outside the settled source policy."""


class SourceUnavailable(IngestionError):
    """An approved source could not be retrieved."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        failure_classification: str = "UNAVAILABLE",
        transport_provenance: SourceTransportProvenance | None = None,
        terminal: bool = False,
    ) -> None:
        super().__init__(message)
        if http_status is not None and not 100 <= http_status <= 599:
            raise ValueError("SourceUnavailable HTTP status must be between 100 and 599.")
        self.http_status = http_status
        self.failure_classification = failure_classification
        self.transport_provenance = transport_provenance
        self.terminal = terminal

    def __str__(self) -> str:
        message = super().__str__()
        if self.transport_provenance is None:
            return message
        record = _canonical_json(self.transport_provenance.to_dict()).decode("utf-8")
        return f"{message} transport={record}"


class SourceRefused(SourceUnavailable):
    """A source denied access or the current authorization does not permit dispatch."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        failure_classification: str = "TECHNICAL_REFUSAL",
        transport_provenance: SourceTransportProvenance | None = None,
    ) -> None:
        super().__init__(
            message,
            http_status=http_status,
            failure_classification=failure_classification,
            transport_provenance=transport_provenance,
            terminal=True,
        )


class SourceDeferred(SourceUnavailable):
    """A provider limit cannot be honored within the configured elapsed budget."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        transport_provenance: SourceTransportProvenance | None = None,
    ) -> None:
        super().__init__(
            message,
            http_status=http_status,
            failure_classification="DEFERRED",
            transport_provenance=transport_provenance,
            terminal=True,
        )


class SourceBudgetExceeded(SourceUnavailable):
    """A configured transport request, byte, timeout or redirect bound was reached."""

    def __init__(
        self,
        message: str,
        *,
        failure_classification: str,
        http_status: int | None = None,
        transport_provenance: SourceTransportProvenance | None = None,
    ) -> None:
        super().__init__(
            message,
            http_status=http_status,
            failure_classification=failure_classification,
            transport_provenance=transport_provenance,
            terminal=True,
        )


class SourceIntegrityError(IngestionError):
    """Retained source bytes or cache metadata failed exact integrity checks."""


@dataclass(frozen=True)
class SourceTransportEndpoint:
    host: str
    path_prefix: str

    def __post_init__(self) -> None:
        host = self.host.casefold().rstrip(".")
        if (
            not host
            or "/" in host
            or not self.path_prefix.startswith("/")
            or ".." in self.path_prefix.split("/")
        ):
            raise ValueError("Source transport endpoints need a public host and absolute path.")
        object.__setattr__(self, "host", host)


@dataclass(frozen=True)
class SourceTransportPolicy:
    allowed_endpoints: tuple[SourceTransportEndpoint, ...] = (
        SourceTransportEndpoint("www.football-data.co.uk", "/mmz4281/"),
        SourceTransportEndpoint("football-data.co.uk", "/mmz4281/"),
        SourceTransportEndpoint("raw.githubusercontent.com", "/openfootball/"),
    )
    allowed_cross_host_redirects: tuple[tuple[str, str], ...] = ()
    max_request_count: int = 64
    max_total_bytes: int = 32 * 1024 * 1024
    per_request_timeout_seconds: float = 30.0
    total_elapsed_budget_seconds: float = 120.0
    minimum_pacing_interval_seconds: float = 1.0
    retry_count: int = 2
    base_backoff_seconds: float = 0.5
    maximum_backoff_seconds: float = 10.0
    redirect_count: int = 3

    def __post_init__(self) -> None:
        if not self.allowed_endpoints:
            raise ValueError("At least one public source endpoint must be configured.")
        if min(self.max_request_count, self.max_total_bytes) <= 0:
            raise ValueError("Source transport request and byte limits must be positive.")
        if self.retry_count < 0 or self.redirect_count < 0:
            raise ValueError("Source transport retry and redirect limits cannot be negative.")
        durations = (
            self.per_request_timeout_seconds,
            self.total_elapsed_budget_seconds,
            self.minimum_pacing_interval_seconds,
            self.base_backoff_seconds,
            self.maximum_backoff_seconds,
        )
        if any(not math.isfinite(value) or value < 0 for value in durations):
            raise ValueError("Source transport time limits must be finite and nonnegative.")
        if min(self.per_request_timeout_seconds, self.total_elapsed_budget_seconds) <= 0:
            raise ValueError("Source transport timeout and elapsed budget must be positive.")
        pairs = tuple(
            (source.casefold().rstrip("."), target.casefold().rstrip("."))
            for source, target in self.allowed_cross_host_redirects
        )
        object.__setattr__(self, "allowed_cross_host_redirects", pairs)


class CurrentSourceAuthorization(Protocol):
    def require_current(self, decision_digest: str) -> dict[str, Any]: ...


class SourceHttpResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def read(self, size: int = -1) -> bytes: ...

    def set_timeout(self, timeout_seconds: float) -> None: ...

    def close(self) -> None: ...


class SourceHttpTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_ips: tuple[str, ...],
    ) -> SourceHttpResponse: ...


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
_OPENFOOTBALL_TEXT_PATHS: Mapping[str, str] = MappingProxyType(
    {
        "premier_league": "england/master/{season}/1-premierleague.txt",
        "serie_a": "italy/master/{season}/1-seriea.txt",
        "la_liga": "espana/master/{season}/1-liga.txt",
        "bundesliga": "deutschland/master/{season}/1-bundesliga.txt",
        "ligue_1": "europe/master/france/{season}_fr1.txt",
        "liga_portugal": "europe/master/portugal/{season}_pt1.txt",
    }
)
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


def openfootball_text_url(league: LeagueConfig, season: str) -> str:
    """Return the upstream OpenFootball.TXT schedule feed for a supported league."""
    path = _OPENFOOTBALL_TEXT_PATHS.get(league.key)
    if path is None or not league.openfootball_supported:
        raise SourcePolicyError(
            f"OpenFootball has no permitted schedule fallback for {league.name}."
        )
    season_code(season)
    return f"https://raw.githubusercontent.com/openfootball/{path.format(season=season)}"


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
    explicit_fixture_status: str | None = None


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


class OpenFootballTextParser:
    """Parse the CC0 upstream Football.TXT schedule format used by OpenFootball."""

    _DATE_LINE = re.compile(
        r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?"
        r"(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?$"
    )
    _TIME_PREFIX = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+(?P<fixture>.+)$")
    _SCORE_SUFFIX = re.compile(
        r"^(?P<teams>.+?)\s+(?P<home>\d{1,2})-(?P<away>\d{1,2})"
        r"(?:\s+\(\d{1,2}-\d{1,2}\))?$"
    )
    _MATCHDAY = re.compile(r"^(?:▪\s*)?(?:Matchday|Regular Season)\s*[- ]?\s*(.+)$")

    def parse(
        self,
        content: bytes | str,
        *,
        league: LeagueConfig,
        season: str,
    ) -> ParsedDataset:
        if not league.openfootball_supported:
            raise SourcePolicyError(
                f"OpenFootball has no permitted schedule fallback for {league.name}."
            )
        season_match = _SEASON_PATTERN.fullmatch(season)
        if season_match is None:
            raise ValueError("Season must use YYYY-YY form, for example 2026-27.")
        start_year = int(season_match.group("start"))
        end_year = start_year + 1
        try:
            text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        except UnicodeDecodeError as error:
            raise SourceParseError("OpenFootball Football.TXT is not UTF-8.") from error
        lines = text.splitlines()
        first_content = next((line.strip() for line in lines if line.strip()), "")
        if not first_content.startswith("="):
            raise SourceParseError("OpenFootball Football.TXT must start with a title line.")

        rows: list[ParsedRow] = []
        active_date: date | None = None
        source_round: str | None = None
        recognized_match_line = False
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("="):
                continue
            matchday = self._MATCHDAY.fullmatch(line)
            if matchday is not None:
                source_round = matchday.group(1).strip() or None
                continue
            date_match = self._DATE_LINE.fullmatch(line)
            if date_match is not None:
                try:
                    month = datetime.strptime(date_match.group("month"), "%b").month
                    year = int(date_match.group("year") or (start_year if month >= 7 else end_year))
                    active_date = date(year, month, int(date_match.group("day")))
                except ValueError as error:
                    raise SourceParseError(
                        f"OpenFootball Football.TXT line {line_number} has an invalid date."
                    ) from error
                continue

            time_match = self._TIME_PREFIX.fullmatch(line)
            time_text = time_match.group("time") if time_match is not None else None
            fixture_text = time_match.group("fixture") if time_match is not None else line
            if " v " not in fixture_text:
                continue
            recognized_match_line = True
            if active_date is None:
                raise SourceParseError(
                    f"OpenFootball Football.TXT line {line_number} has no preceding date."
                )
            home, away = (part.strip() for part in fixture_text.split(" v ", maxsplit=1))
            score: dict[object, object] = {}
            score_match = self._SCORE_SUFFIX.fullmatch(away)
            if score_match is not None:
                away = score_match.group("teams").strip()
                score["ft"] = [int(score_match.group("home")), int(score_match.group("away"))]
            if not home or not away:
                raise SourceParseError(
                    f"OpenFootball Football.TXT line {line_number} has an empty team name."
                )
            kickoff, local_date, local_text, precision, warnings = _kickoff(
                league, active_date.isoformat(), time_text
            )
            rows.append(
                ParsedRow(
                    source_row_key=f"line-{line_number}",
                    home_team=home,
                    away_team=away,
                    kickoff_utc=kickoff,
                    kickoff_local_date=local_date,
                    kickoff_local_text=local_text,
                    kickoff_precision=precision,
                    fields=MappingProxyType(_openfootball_fields(score)),
                    raw_fields=MappingProxyType(
                        {
                            "date": active_date.isoformat(),
                            "time": time_text or "",
                            "team1": home,
                            "team2": away,
                            "score": _json_scalar(score) if score else "{}",
                        }
                    ),
                    source_round=source_round,
                    parse_warnings=warnings,
                )
            )
        if not rows and recognized_match_line:
            raise SourceParseError("OpenFootball Football.TXT contains no valid fixture rows.")
        return ParsedDataset(
            SourceKind.OPENFOOTBALL_TEXT, league, season, tuple(rows), "openfootball-footballtxt"
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


class _TeamRegistrationDisposition(StrEnum):
    NONE = "NONE"
    SOURCE_NAME = "SOURCE_NAME"
    REVIEWED_TARGET = "REVIEWED_TARGET"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class _TeamIdentityEvidence:
    resolution: TeamResolution
    registration_disposition: _TeamRegistrationDisposition
    registry_entry: ApprovedAlias | ApprovedProLeagueAlias | None = None
    registry_rule_version: str | None = None


@dataclass
class TeamCanonicalizer:
    """Pure in-memory name mapping utility; import identity comes from the database."""

    _canonical_names: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    _aliases: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def register_team(self, league: LeagueConfig, canonical_name: str, *aliases: str) -> str:
        normalized = canonical_key(canonical_name)
        team_id = deterministic_identifier("team", f"{league.key}:{normalized}")
        self._canonical_names[(league.key, team_id)] = (team_id, canonical_name)
        for alias in (canonical_name, *aliases):
            self.register_alias(league, alias, team_id)
        return team_id

    def register_existing_team(
        self, league: LeagueConfig, team_id: str, canonical_name: str
    ) -> None:
        self._canonical_names[(league.key, team_id)] = (team_id, canonical_name)
        self.register_alias(league, canonical_name, team_id)

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
    transport_provenance: SourceTransportProvenance | None = None


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
    transport_provenance_json: str | None = None


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
class FixtureCaptureObservation:
    source_row_key: str
    fixture_id: str | None
    revision_id: str | None
    revision_digest: str | None
    kickoff_utc: str | None
    kickoff_local_date: date | None
    source_assertion_ids: tuple[str, ...]
    identity_state: MappingState
    reason_code: str | None = None


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
                "GLOSSARY.md: Football-Data.co.uk restricted private local noncommercial use"
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
        SourceKind.OPENFOOTBALL_TEXT: _SourceRights(
            source_key="openfootball-footballtxt",
            canonical_name="OpenFootball Football.TXT",
            owner="OpenFootball",
            source_class="OPEN_DATASET",
            access_method="DIRECT_RAW_TEXT",
            base_locator="https://raw.githubusercontent.com/openfootball/",
            allowed_use="CC0",
            retention_status="RETAIN_REUSABLE",
            redistributable=True,
            terms_reference="https://creativecommons.org/publicdomain/zero/1.0/",
            artifact_retention_class="REUSABLE",
        ),
        SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION_V2: _SourceRights(
            source_key="official-fixture-manual-citation-v2",
            canonical_name="Official scheduling publication, manual citation v2",
            owner="Official competition publishers",
            source_class="OFFICIAL_COMPETITION",
            access_method="MANUAL_CITATION",
            base_locator="matchvet:operator-official-fixture-observation:2",
            allowed_use="RESEARCH_ONLY",
            retention_status="RETAIN_PRIVATE",
            redistributable=False,
            terms_reference="matchvet:operator-official-fixture-observation:2",
            artifact_retention_class="PROTECTED",
        ),
        SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION: _SourceRights(
            source_key="pro-league-official-manual-citation",
            canonical_name="Pro League official publication, manual citation",
            owner="Pro League",
            source_class="OFFICIAL_COMPETITION",
            access_method="MANUAL_CITATION",
            base_locator="https://www.proleague.be/",
            allowed_use="RESEARCH_ONLY",
            retention_status="RETAIN_PRIVATE",
            redistributable=False,
            terms_reference="matchvet:operator-official-fixture-observation:1",
            artifact_retention_class="PROTECTED",
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
        team_alias_registry: TeamAliasRegistry | None = None,
        pro_league_team_alias_registry: ProLeagueTeamAliasRegistry | None = None,
    ) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Fixture history import requires a healthy writable store.")
        self._store = store
        self._private_root = private_root.resolve()
        from dataclasses import asdict

        from matchvet.pro_league_team_alias_registry import (
            ProLeagueTeamAliasRegistry,
            default_pro_league_registry,
        )
        from matchvet.team_alias_registry import TeamAliasRegistry, default_registry

        if team_alias_registry is None:
            self._team_alias_registry = default_registry()
        else:
            self._team_alias_registry = TeamAliasRegistry.from_json(
                _canonical_json(
                    {
                        "version": team_alias_registry.version,
                        "digest": team_alias_registry.digest,
                        "entries": [asdict(entry) for entry in team_alias_registry.entries],
                    }
                )
            )
        if pro_league_team_alias_registry is None:
            self._pro_league_team_alias_registry = default_pro_league_registry()
        else:
            self._pro_league_team_alias_registry = ProLeagueTeamAliasRegistry.from_json(
                _canonical_json(
                    {
                        "version": pro_league_team_alias_registry.version,
                        "digest": pro_league_team_alias_registry.digest,
                        "entries": [
                            asdict(entry) for entry in pro_league_team_alias_registry.entries
                        ],
                    }
                )
            )
        self._artifacts = ArtifactStore(store)

    def import_dataset(
        self,
        dataset: ParsedDataset,
        content: bytes,
        capture: SourceCaptureInput,
        *,
        identity_policy: TeamIdentityPolicy = TeamIdentityPolicy.REGISTER_UNKNOWN,
        scheduled_rows_known_only: bool = False,
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
        transport = capture.transport_provenance
        if transport is not None and (
            transport.requested_url != capture.source_url
            or transport.retrieved_at_utc != captured_at
            or transport.response_status != capture.response_status
            or transport.content_digest != digest
            or transport.content_byte_count != len(content)
        ):
            raise SourceIntegrityError(
                "Capture transport provenance differs from exact response bytes."
            )
        rights_metadata: dict[str, object] = {
            "allowed_use": source_rights.allowed_use,
            "redistributable": source_rights.redistributable,
            "retention_status": source_rights.retention_status,
            "source_kind": dataset.source_kind.value,
        }
        if transport is not None:
            rights_metadata["transport"] = transport.to_dict()
        cache_key = capture.cache_key or (
            f"{source_rights.source_key}:{dataset.league.key}:{dataset.season}:{capture.source_url}"
        )
        existing = self._existing_capture(source_id, cache_key, digest, captured_at)
        if existing is not None:
            return ImportResult(
                source_capture_id=existing.capture_id,
                source_digest=digest,
                league_key=dataset.league.key,
                season=dataset.season,
                fixtures_seen=len(dataset.rows),
                fixtures_imported=0,
                revisions_appended=0,
                statistics_imported=0,
                unknown_fields=0,
                duplicate_rows=len(dataset.rows),
                unresolved_rows=0,
                conflicts=0,
                from_existing_capture=True,
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
                    _canonical_json(rights_metadata).decode("utf-8"),
                    "matchvet-t06-v1",
                    captured_at,
                ),
            )
            seen_row_fingerprints: set[str] = set()
            rows = (
                tuple(sorted(dataset.rows, key=lambda row: _fixture_status(row) != "COMPLETED"))
                if scheduled_rows_known_only
                else dataset.rows
            )
            for row_number, row in enumerate(rows, start=1):
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
                    (
                        TeamIdentityPolicy.KNOWN_ONLY
                        if scheduled_rows_known_only and _fixture_status(row) != "COMPLETED"
                        else identity_policy
                    ),
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

    def retain_capture(
        self,
        *,
        source_kind: SourceKind,
        league: LeagueConfig,
        season: str,
        content: bytes,
        capture: SourceCaptureInput,
    ) -> SourceCaptureRecord:
        """Retain source bytes and rights metadata without parsing source rows."""
        result = self.import_dataset(
            ParsedDataset(source_kind, league, season, (), "capture-only"),
            content,
            capture,
        )
        record = next(
            item for item in self.source_captures() if item.capture_id == result.source_capture_id
        )
        return record

    def observations_for_capture(self, capture_id: str) -> tuple[FixtureCaptureObservation, ...]:
        """Return only fixture rows and revisions linked to one source capture."""
        connection = self._store._connection_for_repository()
        resolved_rows = connection.execute(
            """
            SELECT sa.source_row_key, f.fixture_id, fr.revision_id, fr.revision_digest,
                   fr.kickoff_utc, fr.kickoff_local_text,
                   group_concat(DISTINCT sa.assertion_id)
            FROM source_assertions AS sa
            JOIN fixture_revision_assertions AS fra ON fra.assertion_id = sa.assertion_id
            JOIN fixture_revisions AS fr ON fr.revision_id = fra.revision_id
            JOIN fixtures AS f ON f.fixture_id = fr.fixture_id
            WHERE sa.capture_id = ?
              AND sa.predicate IN ('kickoff', 'home_team', 'away_team', 'fixture_status')
            GROUP BY sa.source_row_key, f.fixture_id, fr.revision_id, fr.revision_digest,
                     fr.kickoff_utc, fr.kickoff_local_text
            ORDER BY sa.source_row_key, fr.revision_id
            """,
            (capture_id,),
        ).fetchall()
        unresolved_rows = connection.execute(
            """
            SELECT u.source_row_key, u.reason,
                   max(CASE WHEN sa.predicate = 'kickoff' THEN sa.normalized_value_json END),
                   group_concat(DISTINCT sa.assertion_id)
            FROM unresolved_fixture_rows AS u
            JOIN source_assertions AS sa
              ON sa.capture_id = u.capture_id AND sa.source_row_key = u.source_row_key
            WHERE u.capture_id = ?
              AND sa.predicate IN ('kickoff', 'home_team', 'away_team', 'fixture_status')
            GROUP BY u.source_row_key, u.reason
            ORDER BY u.source_row_key
            """,
            (capture_id,),
        ).fetchall()
        observations: list[FixtureCaptureObservation] = [
            FixtureCaptureObservation(
                source_row_key=str(row[0]),
                fixture_id=str(row[1]),
                revision_id=str(row[2]),
                revision_digest=str(row[3]),
                kickoff_utc=str(row[4]) if row[4] is not None else None,
                kickoff_local_date=_parse_date(str(row[5])) if row[5] is not None else None,
                source_assertion_ids=tuple(sorted(str(row[6]).split(","))),
                identity_state=MappingState.CONFIRMED,
            )
            for row in resolved_rows
        ]
        for row in unresolved_rows:
            kickoff_utc: str | None = None
            kickoff_local_date: date | None = None
            try:
                normalized_kickoff = json.loads(str(row[2])) if row[2] is not None else None
            except json.JSONDecodeError:
                normalized_kickoff = None
            if isinstance(normalized_kickoff, str):
                if "T" in normalized_kickoff:
                    try:
                        parsed_kickoff = datetime.fromisoformat(
                            normalized_kickoff.replace("Z", "+00:00")
                        )
                        if parsed_kickoff.tzinfo is not None:
                            kickoff_utc = parsed_kickoff.astimezone(UTC).isoformat()
                    except ValueError:
                        kickoff_utc = None
                else:
                    kickoff_local_date = _parse_date(normalized_kickoff)
            observations.append(
                FixtureCaptureObservation(
                    source_row_key=str(row[0]),
                    fixture_id=None,
                    revision_id=None,
                    revision_digest=None,
                    kickoff_utc=kickoff_utc,
                    kickoff_local_date=kickoff_local_date,
                    source_assertion_ids=tuple(sorted(str(row[3]).split(","))),
                    identity_state=MappingState.UNKNOWN,
                    reason_code=str(row[1]),
                )
            )
        return tuple(sorted(observations, key=lambda item: item.source_row_key))

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
                   s.redistributable, c.observed_terms, c.terms_reference, c.rights_json
            FROM source_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            ORDER BY c.retrieved_at_utc, c.capture_id
            """
        ).fetchall()
        records: list[SourceCaptureRecord] = []
        for row in rows:
            transport_json = None
            rights_json = str(row[13])
            if '"transport":' in rights_json:
                try:
                    rights = json.loads(rights_json)
                except (ValueError, TypeError) as error:
                    raise SourceIntegrityError(
                        "Source capture rights metadata is malformed."
                    ) from error
            else:
                rights = None
            if isinstance(rights, dict) and "transport" in rights:
                provenance = SourceTransportProvenance.from_dict(rights["transport"])
                transport_json = _canonical_json(provenance.to_dict()).decode("utf-8")
            records.append(
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
                    transport_provenance_json=transport_json,
                )
            )
        return tuple(records)

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

    def resolve_existing_team(
        self,
        league: LeagueConfig,
        season: str,
        source_name: str,
        *,
        source_kind: SourceKind = SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION,
    ) -> TeamResolution:
        """Resolve one source name through the normal known-only LF03 rules."""
        season_code(season)
        connection = self._store._connection_for_repository()
        return self._resolve_team_evidence(
            connection,
            league,
            season,
            source_name,
            source_kind,
        ).resolution

    def _resolve_team_evidence(
        self,
        database: StoreTransaction | sqlite3.Connection,
        league: LeagueConfig,
        season: str,
        source_name: str,
        source_kind: SourceKind,
    ) -> _TeamIdentityEvidence:
        """Resolve every supported current identity before registration policy applies."""
        from matchvet.pro_league_team_alias_registry import LEAGUE_KEY, SEASON
        from matchvet.team_alias_registry import source_lineage

        normalized = canonical_key(source_name)
        league_id = deterministic_identifier("league", league.key)
        rows = database.execute(
            """
            SELECT DISTINCT t.team_id, t.canonical_name
            FROM teams AS t
            LEFT JOIN team_aliases AS a
              ON a.team_id = t.team_id AND a.league_id = t.league_id
            WHERE t.league_id = ?
              AND (t.normalized_name = ? OR a.normalized_alias = ?)
            """,
            (league_id, normalized, normalized),
        ).fetchall()
        current_team_ids = {str(row[0]) for row in rows}
        evidence: set[str] = set(current_team_ids)
        names = {str(row[0]): str(row[1]) for row in rows}
        registry: TeamAliasRegistry | ProLeagueTeamAliasRegistry | None
        if source_kind is SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION:
            registry = self._pro_league_team_alias_registry
        elif source_kind in (SourceKind.OPENFOOTBALL, SourceKind.OPENFOOTBALL_TEXT):
            registry = self._team_alias_registry
        else:
            registry = None
        registry_entries = (
            registry.candidates(league.key, season, source_lineage(source_kind), source_name)
            if registry is not None
            else ()
        )
        if len(registry_entries) > 1:
            return _TeamIdentityEvidence(
                TeamResolution(MappingState.AMBIGUOUS, source_name, None, None),
                _TeamRegistrationDisposition.NONE,
            )
        registry_entry = registry_entries[0] if registry_entries else None
        registry_rule_version = (
            f"{registry.version}:{registry.digest}"
            if registry is not None
            and (
                registry_entry is not None
                or (
                    source_kind is SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION
                    and league.key == LEAGUE_KEY
                    and season == SEASON
                )
            )
            else None
        )
        registry_target_missing = False
        registry_target_invalid = False
        if registry_entry is not None:
            target = database.execute(
                "SELECT league_id, canonical_name FROM teams WHERE team_id = ?",
                (registry_entry.team_id,),
            ).fetchone()
            if target is None:
                registry_target_missing = True
            elif str(target[0]) != league_id or str(target[1]) != registry_entry.canonical_name:
                registry_target_invalid = True
            else:
                evidence.add(registry_entry.team_id)
                names[registry_entry.team_id] = registry_entry.canonical_name
        candidates = tuple(sorted(evidence))
        if len(candidates) > 1:
            return _TeamIdentityEvidence(
                TeamResolution(MappingState.AMBIGUOUS, source_name, None, None, candidates),
                _TeamRegistrationDisposition.NONE,
                registry_entry,
                registry_rule_version,
            )
        if registry_target_invalid or (registry_target_missing and current_team_ids):
            return _TeamIdentityEvidence(
                TeamResolution(MappingState.UNKNOWN, source_name, None, None),
                _TeamRegistrationDisposition.BLOCKED,
                registry_entry,
                registry_rule_version,
            )
        if registry_target_missing:
            return _TeamIdentityEvidence(
                TeamResolution(MappingState.UNKNOWN, source_name, None, None),
                (
                    _TeamRegistrationDisposition.BLOCKED
                    if source_kind is SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION
                    else _TeamRegistrationDisposition.REVIEWED_TARGET
                ),
                registry_entry,
                registry_rule_version,
            )
        if len(candidates) == 1:
            team_id = candidates[0]
            return _TeamIdentityEvidence(
                TeamResolution(
                    MappingState.CONFIRMED,
                    source_name,
                    team_id,
                    names[team_id],
                    candidates,
                ),
                _TeamRegistrationDisposition.NONE,
                registry_entry,
                registry_rule_version,
            )
        return _TeamIdentityEvidence(
            TeamResolution(MappingState.UNKNOWN, source_name, None, None),
            _TeamRegistrationDisposition.SOURCE_NAME,
            registry_entry,
            registry_rule_version,
        )

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
        identity_policy: TeamIdentityPolicy,
        season: str,
        source_kind: SourceKind,
    ) -> TeamResolution:
        evidence = self._resolve_team_evidence(tx, league, season, source_name, source_kind)
        resolution = evidence.resolution
        if identity_policy is TeamIdentityPolicy.REGISTER_UNKNOWN:
            if evidence.registration_disposition is _TeamRegistrationDisposition.SOURCE_NAME:
                team_id = deterministic_identifier(
                    "team", f"{league.key}:{canonical_key(source_name)}"
                )
                resolution = TeamResolution(
                    MappingState.CONFIRMED,
                    source_name,
                    team_id,
                    source_name,
                )
            elif evidence.registration_disposition is _TeamRegistrationDisposition.REVIEWED_TARGET:
                assert evidence.registry_entry is not None
                resolution = TeamResolution(
                    MappingState.CONFIRMED,
                    source_name,
                    evidence.registry_entry.team_id,
                    evidence.registry_entry.canonical_name,
                    (evidence.registry_entry.team_id,),
                )
        if resolution.state is not MappingState.CONFIRMED:
            self._insert_source_team_mapping(
                tx,
                league,
                source_name,
                source_id,
                league_id,
                resolution,
                captured_at,
                identity_policy,
                registry_rule_version=evidence.registry_rule_version,
            )
            return resolution
        assert resolution.canonical_team_id is not None
        canonical_name = resolution.canonical_name or source_name
        if identity_policy is TeamIdentityPolicy.KNOWN_ONLY:
            self._insert_source_team_mapping(
                tx,
                league,
                source_name,
                source_id,
                league_id,
                resolution,
                captured_at,
                identity_policy,
                registry_rule_version=evidence.registry_rule_version,
            )
            return resolution
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
        if evidence.registry_entry is None:
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
            tx,
            league,
            source_name,
            source_id,
            league_id,
            resolution,
            captured_at,
            identity_policy,
            registry_rule_version=evidence.registry_rule_version,
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
        identity_policy: TeamIdentityPolicy,
        *,
        registry_rule_version: str | None,
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
                (
                    registry_rule_version
                    or (
                        f"{self._team_alias_registry.version}:{self._team_alias_registry.digest}"
                        if identity_policy is TeamIdentityPolicy.KNOWN_ONLY
                        else "matchvet-t06-team-v1"
                    )
                ),
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
        identity_policy: TeamIdentityPolicy,
    ) -> None:
        home = self._resolve_team(
            tx,
            dataset.league,
            row.home_team,
            source_id,
            league_id,
            captured_at,
            identity_policy,
            dataset.season,
            dataset.source_kind,
        )
        away = self._resolve_team(
            tx,
            dataset.league,
            row.away_team,
            source_id,
            league_id,
            captured_at,
            identity_policy,
            dataset.season,
            dataset.source_kind,
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
        if row.explicit_fixture_status is not None:
            revision_assertions.append(assertions["fixture_status"])
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
            "kickoff_utc": (
                row.kickoff_utc.astimezone(UTC).isoformat()
                if row.kickoff_utc is not None and row.kickoff_precision != "DATE"
                else None
            ),
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
        if row.explicit_fixture_status is not None:
            self._record_conflict(
                tx, "FIXTURE", fixture_id, "fixture_status", assertions["fixture_status"]
            )
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
        if row.kickoff_precision == "DATE":
            if row.kickoff_local_date is not None:
                kickoff_value = row.kickoff_local_date.isoformat()
        elif row.kickoff_utc is not None:
            if row.kickoff_utc.tzinfo is None or row.kickoff_utc.utcoffset() is None:
                raise ValueError("Source kickoff instants must include a UTC offset.")
            kickoff_value = row.kickoff_utc.astimezone(UTC).isoformat()
        elif row.kickoff_local_date is not None:
            kickoff_value = row.kickoff_local_date.isoformat()
        kickoff_timestamp = (
            row.kickoff_utc.astimezone(UTC).isoformat()
            if row.kickoff_precision != "DATE" and row.kickoff_utc is not None
            else None
        )
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
        if row.explicit_fixture_status is not None:
            fields["fixture_status"] = (
                ParsedField("fixture_status", OBSERVED, row.explicit_fixture_status),
                "FixtureStatus",
                row.explicit_fixture_status,
            )
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
                if predicate in {"home_team", "away_team", "kickoff", "fixture_status"}
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
                    kickoff_timestamp if predicate == "kickoff" else None,
                    kickoff_timestamp if predicate == "kickoff" else None,
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


def _canonical_f01_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Provider attempt timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _scheduled_provider_attempt(
    *,
    scope_id: str,
    provider_id: str,
    state: ProviderAttemptState,
    attempted_at_utc: str,
    http_status: int | None,
    capture_id: str | None,
    capture_digest: str | None,
) -> ProviderAttempt:
    from matchvet.fixture_coverage import ProviderAttempt

    identity = ":".join(
        (
            scope_id,
            provider_id,
            state.value,
            attempted_at_utc,
            str(http_status) if http_status is not None else "",
            capture_id or "",
            capture_digest or "",
        )
    )
    return ProviderAttempt(
        attempt_id=deterministic_identifier("provider_attempt", identity),
        scope_id=scope_id,
        provider_id=provider_id,
        capability_id="scheduled-fixtures",
        state=state,
        retrieved_at_utc=attempted_at_utc,
        http_status=http_status,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )


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
    if row.explicit_fixture_status is not None:
        return row.explicit_fixture_status
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
    transport_provenance: SourceTransportProvenance | None = None


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


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, addresses: tuple[str, ...], *, timeout: float) -> None:
        context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=timeout, context=context)
        self._tls_context = context
        self._addresses = addresses
        self._connect_timeout = timeout

    def connect(self) -> None:
        if not self._addresses:
            raise OSError("No validated public address is available for the source host.")
        deadline = time_module.monotonic() + self._connect_timeout
        address = self._addresses[0]
        remaining = deadline - time_module.monotonic()
        if remaining <= 0:
            raise TimeoutError("Source connection exceeded its request timeout.")
        ip = ipaddress.ip_address(address)
        family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        sockaddr: tuple[object, ...] = (
            (address, self.port) if ip.version == 4 else (address, self.port, 0, 0)
        )
        connection = socket.socket(family, socket.SOCK_STREAM)
        connection.settimeout(remaining)
        try:
            connection.connect(sockaddr)
            remaining = deadline - time_module.monotonic()
            if remaining <= 0:
                raise TimeoutError("Source connection exceeded its request timeout.")
            connection.settimeout(remaining)
            self.sock = self._tls_context.wrap_socket(connection, server_hostname=self.host)
        except OSError:
            connection.close()
            raise


class _PinnedHTTPResponse:
    def __init__(self, connection: _PinnedHTTPSConnection, response: http.client.HTTPResponse):
        self.connection = connection
        self.response = response
        self.status = response.status
        self.headers = {key.casefold(): value for key, value in response.getheaders()}

    def read(self, size: int = -1) -> bytes:
        return self.response.read(size)

    def set_timeout(self, timeout_seconds: float) -> None:
        if self.connection.sock is not None:
            self.connection.sock.settimeout(timeout_seconds)

    def close(self) -> None:
        self.response.close()
        self.connection.close()


class _PinnedHTTPSTransport:
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_ips: tuple[str, ...],
    ) -> SourceHttpResponse:
        parsed = urlsplit(url)
        connection = _PinnedHTTPSConnection(
            parsed.hostname or "", resolved_ips, timeout=timeout_seconds
        )
        path = parsed.path or "/"
        try:
            connection.request(
                "GET",
                path,
                headers={**headers, "Connection": "close", "Accept-Encoding": "identity"},
            )
            return _PinnedHTTPResponse(connection, connection.getresponse())
        except Exception:
            connection.close()
            raise


class _IncompleteSourceBody(OSError):
    def __init__(self, message: str, *, bytes_received: int) -> None:
        super().__init__(errno.ECONNRESET, message)
        self.bytes_received = bytes_received


def _resolve_public_source_ips(host: str, *, timeout_seconds: float = 30.0) -> tuple[str, ...]:
    result: queue.Queue[tuple[str, ...] | Exception] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            addresses = tuple(sorted({str(record[4][0]) for record in records}))
            result.put(addresses)
        except Exception as error:
            result.put(error)

    worker = threading.Thread(target=resolve, name="matchvet-source-dns", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError("Public source DNS resolution exceeded its request timeout.")
    outcome = result.get_nowait()
    if isinstance(outcome, Exception):
        raise outcome
    return _validate_public_ips(outcome)


def _validate_public_ips(addresses: tuple[str, ...]) -> tuple[str, ...]:
    if not addresses:
        raise SourcePolicyError("The approved source host has no DNS addresses.")
    try:
        parsed = tuple((ipaddress.ip_address(address), address) for address in set(addresses))
    except ValueError as error:
        raise SourcePolicyError("The approved source host has an invalid DNS address.") from error
    if not all(address.is_global for address, _original in parsed):
        raise SourcePolicyError("The approved source host resolves to a nonpublic address.")
    return tuple(
        original
        for _address, original in sorted(parsed, key=lambda pair: (pair[0].version, int(pair[0])))
    )


_TRANSIENT_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTUNREACH,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
}
_TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_REFUSAL_TEXT = (
    "verify you are human",
    "prove you are human",
    "complete the captcha",
    "captcha required",
    "solve the captcha",
    "automated requests",
    "bot detected",
    "bot detection",
    "unusual traffic",
    "access denied",
    "request blocked",
    "blocked by security",
    "web application firewall",
    "cloudflare ray id",
    "authentication required",
    "login required",
    "sign in to continue",
    "subscribe to continue",
    "subscription required",
    "paywall",
    "you have been banned",
    "your ip has been banned",
    "account suspended",
    "access permanently blocked",
)


def _refusal_reason(
    status: int,
    headers: Mapping[str, str],
    body: bytes = b"",
    target_url: str | None = None,
) -> str | None:
    if status in {401, 402, 403, 407, 451}:
        return {
            401: "AUTHENTICATION_REFUSED",
            402: "PAYWALL_REFUSED",
            403: "ACCESS_REFUSED",
            407: "PROXY_AUTHENTICATION_REFUSED",
            451: "ACCESS_REFUSED",
        }[status]
    if any(key.casefold() == "www-authenticate" for key in headers):
        return "AUTHENTICATION_CHALLENGE"
    if any(
        key.casefold() in {"cf-mitigated", "x-sucuri-block", "x-waf-blocked"} for key in headers
    ):
        return "WAF_OR_ANTIBOT_REFUSAL"
    if target_url is not None:
        path_parts = {item.casefold() for item in urlsplit(target_url).path.split("/") if item}
        if path_parts & {"login", "signin", "sign-in", "auth", "authenticate"}:
            return "LOGIN_REDIRECT_REFUSED"
    text = body[:512_000].decode("utf-8", errors="ignore").casefold()
    if any(phrase in text for phrase in _REFUSAL_TEXT):
        return "TECHNICAL_REFUSAL"
    return None


def _is_transient_exception(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout, http.client.RemoteDisconnected)):
        return True
    if isinstance(error, socket.gaierror):
        return error.errno == socket.EAI_AGAIN
    if isinstance(error, http.client.IncompleteRead):
        return True
    return isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(int(value.strip()))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except TypeError, ValueError, OverflowError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        seconds = (parsed.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
    return max(0.0, seconds)


class ResumableSourceDownloader:
    """Fetch scoped public sources with current authority, bounded transport and private replay."""

    def __init__(
        self,
        private_root: Path,
        *,
        max_source_bytes: int = 32 * 1024 * 1024,
        network_cap_bytes: int | None = None,
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: int = 6 * 60 * 60,
        cache_storage_cap_bytes: int = SETTLED_RESOURCE_BUDGET.managed_storage_cap_bytes,
        policy: SourceTransportPolicy | None = None,
        authorization_repository: CurrentSourceAuthorization | None = None,
        http_transport: SourceHttpTransport | None = None,
        resolve_public_ips: Callable[[str], tuple[str, ...]] | None = None,
        monotonic: Callable[[], float] = time_module.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        selected_network_cap = (
            network_cap_bytes
            if network_cap_bytes is not None
            else SETTLED_RESOURCE_BUDGET.routine_network_bytes
        )
        if (
            min(max_source_bytes, selected_network_cap, cache_ttl_seconds, cache_storage_cap_bytes)
            <= 0
        ):
            raise ValueError("Downloader limits must be positive.")
        if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
            raise ValueError("Downloader timeout must be finite and positive.")
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
        self.policy = policy or SourceTransportPolicy(per_request_timeout_seconds=timeout_seconds)
        self.authorization_repository = authorization_repository
        self.http_transport = http_transport or _PinnedHTTPSTransport()
        self._resolve_public_ips = resolve_public_ips
        self._monotonic = monotonic
        self._utcnow = utcnow
        self._sleep = sleep
        self.network_bytes = 0
        self.network_requests = 0
        self._last_request_started_at: float | None = None

    def configure_for_plan(self, *, historical: bool) -> None:
        if self._network_cap_explicit:
            return
        self.network_cap_bytes = (
            SETTLED_RESOURCE_BUDGET.historical_network_bytes
            if historical
            else SETTLED_RESOURCE_BUDGET.routine_network_bytes
        )

    def fetch(
        self,
        url: str,
        *,
        cache_key: str,
        refresh: bool = False,
        authorization_decision_digest: str | None = None,
    ) -> DownloadedSource:
        self._validate_url(url)
        data_path, meta_path, part_path = self._paths(cache_key)
        cached = self._read_cache(data_path, meta_path, expected_url=url)
        if cached is not None and not refresh and self._cache_is_fresh(cached):
            return cached

        start = self._monotonic()
        attempts: list[SourceTransportAttempt] = []
        redirects: list[SourceRedirect] = []
        if self.authorization_repository is None or not authorization_decision_digest:
            raise self._refused(
                url,
                start,
                attempts,
                redirects,
                "A separately supplied current source authorization is required before live fetch.",
                "AUTHORIZATION_REQUIRED",
            )
        try:
            auth_entry = self._current_authorized_entry(url, authorization_decision_digest)
        except Exception as error:
            raise self._refused(
                url,
                start,
                attempts,
                redirects,
                "Current source authorization is invalid or withdrawn; live fetch refused.",
                "AUTHORIZATION_INVALID",
            ) from error

        offset = part_path.stat().st_size if part_path.exists() else 0
        if offset > self.max_source_bytes:
            raise SourceIntegrityError("Retained partial source exceeds its byte bound.")
        current_url = url
        current_ips: tuple[str, ...] | None = None
        visited = {url}
        request_count = 0
        operation_bytes = 0
        retry_count = 0
        final_content_type = "application/octet-stream"

        while True:
            self._require_elapsed(start, attempts, redirects, current_url)
            entry_limits = self._authorization_limits(auth_entry)
            self._require_request_budget(
                start,
                attempts,
                redirects,
                current_url,
                request_count,
                operation_bytes,
                entry_limits,
            )
            self._pace(start, attempts, redirects, current_url)
            try:
                auth_entry = self._current_authorized_entry(url, authorization_decision_digest)
            except Exception as error:
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Current source authorization changed before destination validation.",
                    "AUTHORIZATION_INVALID",
                ) from error
            if current_ips is None:
                try:
                    current_ips = self._resolve_destination(
                        urlsplit(current_url).hostname or "",
                        start,
                        attempts,
                        redirects,
                        current_url,
                        entry_limits,
                    )
                except SourcePolicyError as error:
                    raise self._refused(
                        url,
                        start,
                        attempts,
                        redirects,
                        str(error),
                        "NONPUBLIC_DESTINATION",
                    ) from error
                except OSError as error:
                    transient = _is_transient_exception(error)
                    attempt = self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        self._monotonic(),
                        self._utc_text(),
                        None,
                        "DNS_TEMPORARY" if transient else "DNS_FAILURE",
                        0,
                    )
                    attempts.append(attempt)
                    if transient and retry_count < self.policy.retry_count:
                        if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                            raise self._budget_failure(
                                url,
                                start,
                                attempts,
                                redirects,
                                "REQUEST_BUDGET_EXHAUSTED",
                            ) from error
                        delay = self._backoff(retry_count)
                        retry_count += 1
                        attempts[-1] = replace(attempt, retry_delay_seconds=delay)
                        self._sleep_with_budget(delay, start, attempts, redirects, current_url)
                        continue
                    raise self._unavailable(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Public source DNS resolution failed.",
                        "DNS_FAILURE",
                    ) from error

            try:
                auth_entry = self._current_authorized_entry(url, authorization_decision_digest)
            except Exception as error:
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Current source authorization changed before HTTP dispatch.",
                    "AUTHORIZATION_INVALID",
                ) from error
            entry_limits = self._authorization_limits(auth_entry)
            remaining = self._remaining(start)
            timeout = min(
                self.policy.per_request_timeout_seconds,
                self.timeout_seconds,
                float(entry_limits["timeout_seconds"]),
                remaining,
            )
            if timeout <= 0:
                raise self._budget_failure(
                    url, start, attempts, redirects, "TOTAL_ELAPSED_BUDGET_EXHAUSTED"
                )
            request_headers = {
                "User-Agent": "MatchVet-T06/1.0",
                "Accept": "application/json,text/plain;q=0.9,text/csv;q=0.8",
            }
            if offset:
                request_headers["Range"] = f"bytes={offset}-"
            request_started = self._monotonic()
            request_started_at = self._utc_text()
            request_deadline = request_started + timeout
            request_count += 1
            self.network_requests += 1
            self._last_request_started_at = request_started
            try:
                response = self.http_transport.request(
                    current_url,
                    headers=request_headers,
                    timeout_seconds=timeout,
                    resolved_ips=current_ips,
                )
            except Exception as error:
                transient = _is_transient_exception(error)
                classification = (
                    "REQUEST_TIMEOUT"
                    if isinstance(error, (TimeoutError, socket.timeout))
                    else "TRANSIENT_TRANSPORT"
                    if transient
                    else "TRANSPORT_FAILURE"
                )
                attempt = self._make_attempt(
                    len(attempts) + 1,
                    current_url,
                    request_started,
                    request_started_at,
                    None,
                    classification,
                    0,
                )
                attempts.append(attempt)
                if transient and retry_count < self.policy.retry_count:
                    if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                        raise self._budget_failure(
                            url,
                            start,
                            attempts,
                            redirects,
                            "REQUEST_BUDGET_EXHAUSTED",
                        ) from error
                    delay = self._backoff(retry_count)
                    retry_count += 1
                    attempts[-1] = replace(attempt, retry_delay_seconds=delay)
                    self._sleep_with_budget(delay, start, attempts, redirects, current_url)
                    continue
                raise self._unavailable(
                    url,
                    start,
                    attempts,
                    redirects,
                    f"Public source transport failed: {error}",
                    "RETRY_EXHAUSTED" if transient and retry_count > 0 else classification,
                ) from error

            status = int(response.status)
            if self._remaining(start) <= 0:
                response.close()
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        "TOTAL_ELAPSED_BUDGET_EXHAUSTED",
                        0,
                    )
                )
                raise self._budget_failure(
                    url,
                    start,
                    attempts,
                    redirects,
                    "TOTAL_ELAPSED_BUDGET_EXHAUSTED",
                    status,
                )
            response_headers = {key.casefold(): value for key, value in response.headers.items()}
            late_redirect_target = None
            if status in {301, 302, 303, 307, 308}:
                location = response_headers.get("location")
                if location:
                    late_redirect_target = urljoin(current_url, location)
            refusal = _refusal_reason(status, response_headers, target_url=late_redirect_target)
            if refusal is not None:
                response.close()
                if late_redirect_target is not None:
                    redirects.append(
                        SourceRedirect(current_url, late_redirect_target, status, False, refusal)
                    )
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        refusal,
                        0,
                    )
                )
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Public source returned a technical access refusal.",
                    refusal,
                    http_status=status,
                )
            if self._monotonic() >= request_deadline:
                response.close()
                retry_after = _retry_after_seconds(
                    response_headers.get("retry-after"), self._utcnow()
                )
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        "REQUEST_TIMEOUT",
                        0,
                        retry_after_seconds=retry_after,
                    )
                )
                if retry_count < self.policy.retry_count:
                    if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                        raise self._budget_failure(
                            url,
                            start,
                            attempts,
                            redirects,
                            self._retry_limit_classification(
                                request_count, operation_bytes, entry_limits
                            ),
                            status,
                        )
                    try:
                        delay = self._retry_delay(retry_count, retry_after, start)
                    except SourceDeferred as error:
                        raise self._deferred_failure(
                            url, start, attempts, redirects, str(error), status
                        ) from error
                    retry_count += 1
                    attempts[-1] = replace(attempts[-1], retry_delay_seconds=delay)
                    self._sleep_with_budget(delay, start, attempts, redirects, current_url)
                    continue
                raise self._unavailable(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Public source response exceeded its per-request timeout.",
                    "REQUEST_TIMEOUT",
                    http_status=status,
                )
            content_type = response_headers.get("content-type", "application/octet-stream").split(
                ";", maxsplit=1
            )[0]
            final_content_type = content_type

            if status in {301, 302, 303, 307, 308}:
                location = response_headers.get("location")
                response.close()
                if not location:
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            "REDIRECT_MISSING_LOCATION",
                            0,
                        )
                    )
                    raise self._unavailable(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Public source redirect omitted its target.",
                        "REDIRECT_MISSING_LOCATION",
                        http_status=status,
                    )
                target_url = urljoin(current_url, location)
                try:
                    auth_entry = self._current_authorized_entry(url, authorization_decision_digest)
                except Exception as error:
                    redirects.append(
                        SourceRedirect(
                            current_url,
                            target_url,
                            status,
                            False,
                            "Current source authorization changed before redirect validation.",
                        )
                    )
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            "AUTHORIZATION_INVALID",
                            0,
                        )
                    )
                    raise self._refused(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Current source authorization changed before redirect validation.",
                        "AUTHORIZATION_INVALID",
                        http_status=status,
                    ) from error
                try:
                    self._validate_url(target_url)
                    source_host = urlsplit(current_url).hostname or ""
                    target_host = urlsplit(target_url).hostname or ""
                    if (
                        source_host.casefold() != target_host.casefold()
                        and (source_host.casefold(), target_host.casefold())
                        not in self.policy.allowed_cross_host_redirects
                    ):
                        raise SourcePolicyError("Cross-host source redirect is not approved.")
                    target_ips = self._resolve_destination(
                        target_host,
                        start,
                        attempts,
                        redirects,
                        target_url,
                        self._authorization_limits(auth_entry),
                    )
                    if target_url in visited:
                        raise SourcePolicyError("Source redirect loop detected.")
                except (SourcePolicyError, OSError, ValueError) as error:
                    redirects.append(
                        SourceRedirect(current_url, target_url, status, False, str(error))
                    )
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            "REDIRECT_REFUSED",
                            0,
                        )
                    )
                    raise self._refused(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Public source redirect target was refused before contact.",
                        "REDIRECT_REFUSED",
                        http_status=status,
                    ) from error
                if len(redirects) >= self.policy.redirect_count:
                    redirects.append(SourceRedirect(current_url, target_url, status, True))
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            "REDIRECT_LIMIT_EXHAUSTED",
                            0,
                        )
                    )
                    raise self._budget_failure(
                        url, start, attempts, redirects, "REDIRECT_LIMIT_EXHAUSTED", status
                    )
                refusal = _refusal_reason(status, response_headers, target_url=target_url)
                if refusal is not None:
                    redirects.append(
                        SourceRedirect(current_url, target_url, status, False, refusal)
                    )
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            refusal,
                            0,
                        )
                    )
                    raise self._refused(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Public source redirected to an authentication or access challenge.",
                        refusal,
                        http_status=status,
                    )
                redirects.append(SourceRedirect(current_url, target_url, status, True))
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        "REDIRECT",
                        0,
                    )
                )
                visited.add(target_url)
                current_url = target_url
                current_ips = target_ips
                offset = 0
                if part_path.exists():
                    part_path.write_bytes(b"")
                continue

            refusal = _refusal_reason(status, response_headers)
            if refusal is not None:
                response.close()
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        refusal,
                        0,
                    )
                )
                self._discard_partial(part_path)
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    f"Public source refused access with HTTP {status}.",
                    refusal,
                    http_status=status,
                )

            if status not in {200, 206}:
                network_bytes_before_sample = self.network_bytes
                try:
                    sample, used = self._read_response_sample(
                        response,
                        start,
                        operation_bytes,
                        entry_limits,
                        request_deadline,
                        64 * 1024,
                    )
                except Exception as error:
                    response.close()
                    received = max(0, self.network_bytes - network_bytes_before_sample)
                    operation_bytes += received
                    transient = _is_transient_exception(error)
                    classification = (
                        "REQUEST_TIMEOUT"
                        if isinstance(error, (TimeoutError, socket.timeout))
                        else "TRANSIENT_ERROR_BODY_FAILURE"
                        if transient
                        else "ERROR_BODY_FAILURE"
                    )
                    retry_after = _retry_after_seconds(
                        response_headers.get("retry-after"), self._utcnow()
                    )
                    attempts.append(
                        self._make_attempt(
                            len(attempts) + 1,
                            current_url,
                            request_started,
                            request_started_at,
                            status,
                            classification,
                            received,
                            retry_after_seconds=retry_after,
                        )
                    )
                    if transient and retry_count < self.policy.retry_count:
                        if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                            raise self._budget_failure(
                                url,
                                start,
                                attempts,
                                redirects,
                                self._retry_limit_classification(
                                    request_count, operation_bytes, entry_limits
                                ),
                                status,
                            ) from error
                        try:
                            sample_retry_delay = self._retry_delay(retry_count, retry_after, start)
                        except SourceDeferred as deferred:
                            raise self._deferred_failure(
                                url,
                                start,
                                attempts,
                                redirects,
                                str(deferred),
                                status,
                            ) from deferred
                        retry_count += 1
                        attempts[-1] = replace(attempts[-1], retry_delay_seconds=sample_retry_delay)
                        self._sleep_with_budget(
                            sample_retry_delay, start, attempts, redirects, current_url
                        )
                        continue
                    raise self._unavailable(
                        url,
                        start,
                        attempts,
                        redirects,
                        f"Public source error response body failed: {error}",
                        classification,
                        http_status=status,
                    ) from error
                operation_bytes += used
                refusal = _refusal_reason(status, response_headers, sample)
                retry_after = _retry_after_seconds(
                    response_headers.get("retry-after"), self._utcnow()
                )
                response.close()
                classification = refusal or ("RATE_LIMIT" if status == 429 else f"HTTP_{status}")
                transient = status in _TRANSIENT_HTTP_STATUSES and refusal is None
                retry_delay: float | None = None
                attempt = self._make_attempt(
                    len(attempts) + 1,
                    current_url,
                    request_started,
                    request_started_at,
                    status,
                    classification,
                    used,
                    response_digest=sha256_bytes(sample),
                    retry_after_seconds=retry_after,
                )
                attempts.append(attempt)
                if refusal is not None:
                    self._discard_partial(part_path)
                    raise self._refused(
                        url,
                        start,
                        attempts,
                        redirects,
                        "Public source returned a technical access refusal.",
                        refusal,
                        http_status=status,
                    )
                if transient and retry_count < self.policy.retry_count:
                    if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                        raise self._budget_failure(
                            url,
                            start,
                            attempts,
                            redirects,
                            self._retry_limit_classification(
                                request_count, operation_bytes, entry_limits
                            ),
                            status,
                        )
                    try:
                        retry_delay = self._retry_delay(retry_count, retry_after, start)
                    except SourceDeferred as error:
                        raise self._deferred_failure(
                            url,
                            start,
                            attempts,
                            redirects,
                            str(error),
                            status,
                        ) from error
                    retry_count += 1
                    attempts[-1] = replace(attempts[-1], retry_delay_seconds=retry_delay)
                    self._sleep_with_budget(retry_delay, start, attempts, redirects, current_url)
                    continue
                raise self._unavailable(
                    url,
                    start,
                    attempts,
                    redirects,
                    f"Public source returned HTTP {status}.",
                    "RETRY_EXHAUSTED" if transient and retry_count > 0 else classification,
                    http_status=status,
                )

            network_bytes_before_response = self.network_bytes
            try:
                _body_size, attempt_bytes, append = self._receive_body(
                    response,
                    status=status,
                    response_headers=response_headers,
                    part_path=part_path,
                    offset=offset,
                    start=start,
                    operation_bytes=operation_bytes,
                    entry_limits=entry_limits,
                    attempts=attempts,
                    redirects=redirects,
                    current_url=current_url,
                    request_deadline=request_deadline,
                )
            except SourceBudgetExceeded as error:
                response.close()
                received = max(0, self.network_bytes - network_bytes_before_response)
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        error.failure_classification,
                        received,
                        response_digest=self._response_digest_from_partial(part_path, received),
                    )
                )
                raise self._budget_failure(
                    url,
                    start,
                    attempts,
                    redirects,
                    error.failure_classification,
                    status,
                ) from error
            except SourceIntegrityError:
                response.close()
                raise
            except Exception as error:
                response.close()
                received = (
                    error.bytes_received
                    if isinstance(error, _IncompleteSourceBody)
                    else max(0, self.network_bytes - network_bytes_before_response)
                )
                operation_bytes += received
                transient = _is_transient_exception(error)
                classification = (
                    "REQUEST_TIMEOUT"
                    if isinstance(error, (TimeoutError, socket.timeout))
                    else "TRANSIENT_BODY_FAILURE"
                    if transient
                    else "BODY_FAILURE"
                )
                attempts.append(
                    self._make_attempt(
                        len(attempts) + 1,
                        current_url,
                        request_started,
                        request_started_at,
                        status,
                        classification,
                        received,
                        response_digest=self._response_digest_from_partial(part_path, received),
                    )
                )
                if transient and retry_count < self.policy.retry_count:
                    if not self._retry_capacity(request_count, operation_bytes, entry_limits):
                        raise self._budget_failure(
                            url,
                            start,
                            attempts,
                            redirects,
                            self._retry_limit_classification(
                                request_count, operation_bytes, entry_limits
                            ),
                            status,
                        ) from error
                    delay = self._backoff(retry_count)
                    retry_count += 1
                    attempts[-1] = replace(attempts[-1], retry_delay_seconds=delay)
                    self._sleep_with_budget(delay, start, attempts, redirects, current_url)
                    offset = part_path.stat().st_size if part_path.exists() else 0
                    continue
                raise self._unavailable(
                    url,
                    start,
                    attempts,
                    redirects,
                    f"Public source response body failed: {error}",
                    "RETRY_EXHAUSTED" if transient and retry_count > 0 else classification,
                    http_status=status,
                ) from error
            else:
                response.close()

            operation_bytes += attempt_bytes
            content = part_path.read_bytes()
            response_body = content[-attempt_bytes:] if attempt_bytes else b""
            refusal = _refusal_reason(status, response_headers, content)
            attempt_classification = refusal or "SUCCESS"
            attempts.append(
                self._make_attempt(
                    len(attempts) + 1,
                    current_url,
                    request_started,
                    request_started_at,
                    status,
                    attempt_classification,
                    attempt_bytes,
                    response_digest=sha256_bytes(response_body),
                )
            )
            if refusal is not None:
                self._discard_partial(part_path)
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Public source response contained a CAPTCHA, WAF, paywall or access challenge.",
                    refusal,
                    http_status=status,
                )
            if not append:
                offset = 0
            retrieved_at = self._utc_text()
            try:
                self._current_authorized_entry(url, authorization_decision_digest)
            except Exception as error:
                self._discard_partial(part_path)
                raise self._refused(
                    url,
                    start,
                    attempts,
                    redirects,
                    "Current source authorization changed before cache admission.",
                    "AUTHORIZATION_INVALID",
                    http_status=status,
                ) from error
            provenance = self._provenance(
                url,
                current_url,
                redirects,
                retrieved_at,
                status,
                sha256_bytes(content[-attempt_bytes:]),
                len(content),
                operation_bytes,
                None,
                retry_count,
                start,
                attempts,
                content_digest=sha256_bytes(content),
            )
            if self._cache_size() + len(_canonical_json(provenance.to_dict())) + 512 > (
                self.cache_storage_cap_bytes
            ):
                raise self._budget_failure(
                    url,
                    start,
                    attempts,
                    redirects,
                    "CACHE_STORAGE_BUDGET_EXHAUSTED",
                    status,
                )
            os.replace(part_path, data_path)
            metadata = {
                "cache_schema": 2,
                "content_sha256": sha256_bytes(content),
                "content_type": final_content_type,
                "retrieved_at_utc": retrieved_at,
                "response_status": status,
                "url": url,
                "transport": provenance.to_dict(),
            }
            self._write_cache_metadata(meta_path, metadata)
            return DownloadedSource(
                content,
                retrieved_at,
                status,
                final_content_type,
                False,
                operation_bytes,
                provenance,
            )

    def inspect_cache(self, cache_key: str) -> DownloadedSource | None:
        """Read retained cache bytes and provenance without a live refresh."""
        data_path, meta_path, _part_path = self._paths(cache_key)
        return self._read_cache(data_path, meta_path)

    def _paths(self, cache_key: str) -> tuple[Path, Path, Path]:
        cache_stem = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return (
            self.cache_root / f"{cache_stem}.data",
            self.cache_root / f"{cache_stem}.json",
            self.cache_root / f"{cache_stem}.part",
        )

    def _cache_is_fresh(self, cached: DownloadedSource) -> bool:
        try:
            retrieved = datetime.fromisoformat(cached.retrieved_at_utc)
        except ValueError as error:
            raise SourceIntegrityError(
                "Retained source cache has an invalid retrieval time."
            ) from error
        if retrieved.utcoffset() is None:
            raise SourceIntegrityError("Retained source cache time lacks a UTC offset.")
        age = (self._utcnow().astimezone(UTC) - retrieved.astimezone(UTC)).total_seconds()
        if age < 0:
            raise SourceIntegrityError("Retained source cache retrieval time is in the future.")
        return age <= self.cache_ttl_seconds

    def _read_cache(
        self, data_path: Path, meta_path: Path, *, expected_url: str | None = None
    ) -> DownloadedSource | None:
        data_exists, meta_exists = data_path.is_file(), meta_path.is_file()
        if not data_exists and not meta_exists:
            return None
        if not data_exists or not meta_exists:
            raise SourceIntegrityError("Retained source cache data and metadata do not match.")
        try:
            raw_bytes = meta_path.read_bytes()
            raw: object = json.loads(raw_bytes)
            content = data_path.read_bytes()
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise SourceIntegrityError(
                "Retained source cache could not be read exactly."
            ) from error
        if not isinstance(raw, dict) or _canonical_json(raw) != raw_bytes:
            raise SourceIntegrityError("Retained source cache metadata is not canonical JSON.")
        required = {"content_sha256", "content_type", "retrieved_at_utc", "response_status", "url"}
        allowed = required | {"cache_schema", "transport"}
        if not required.issubset(raw) or set(raw) - allowed:
            raise SourceIntegrityError("Retained source cache metadata has an unsupported shape.")
        cache_schema = raw.get("cache_schema")
        if ("cache_schema" in raw and cache_schema != 2) or (
            cache_schema == 2 and ("transport" not in raw or raw["transport"] is None)
        ):
            raise SourceIntegrityError("Retained source cache metadata has an unsupported shape.")
        digest = raw.get("content_sha256")
        requested_url = raw.get("url")
        retrieved = raw.get("retrieved_at_utc")
        content_type = raw.get("content_type")
        status = raw.get("response_status")
        if (
            not isinstance(digest, str)
            or digest != sha256_bytes(content)
            or not isinstance(requested_url, str)
            or not isinstance(retrieved, str)
            or not isinstance(content_type, str)
            or type(status) is not int
            or status not in {200, 206}
        ):
            raise SourceIntegrityError("Retained source cache digest or metadata is invalid.")
        self._validate_url(requested_url)
        if expected_url is not None and expected_url != requested_url:
            raise SourceIntegrityError("Retained source cache belongs to a different request URL.")
        try:
            datetime.fromisoformat(retrieved)
        except ValueError as error:
            raise SourceIntegrityError(
                "Retained source cache has an invalid retrieval time."
            ) from error
        provenance = None
        raw_provenance = raw.get("transport")
        if raw_provenance is not None:
            provenance = SourceTransportProvenance.from_dict(raw_provenance)
            if (
                provenance.requested_url != requested_url
                or provenance.response_status != status
                or provenance.content_digest != digest
                or provenance.content_byte_count != len(content)
                or provenance.retrieved_at_utc != retrieved
            ):
                raise SourceIntegrityError("Cache provenance differs from retained response bytes.")
        return DownloadedSource(content, retrieved, status, content_type, True, 0, provenance)

    def _current_authorized_entry(self, requested_url: str, decision_digest: str) -> dict[str, Any]:
        if self.authorization_repository is None:
            raise SourcePolicyError("No current source authorization repository was supplied.")
        manifest = self.authorization_repository.require_current(decision_digest)
        if (
            manifest.get("contract") != "research-source-use-manifest-v1"
            or manifest.get("purpose") != "RESEARCH_ONLY"
            or manifest.get("issue") != 70
            or manifest.get("stage") != "ACQUISITION"
            or not isinstance(manifest.get("entries"), list)
            or len(manifest["entries"]) != 1
            or not isinstance(manifest["entries"][0], dict)
        ):
            raise SourcePolicyError("Current source authority is not an exact acquisition intent.")
        entry = manifest["entries"][0]
        operations = entry.get("requested_operations")
        if (
            entry.get("endpoint") != requested_url
            or entry.get("source_type")
            not in {"AUTOMATED_API", "AUTOMATED_DATASET", "AUTOMATED_PUBLIC_PAGE"}
            or entry.get("access_type") != "PUBLIC"
            or not isinstance(operations, list)
            or not {
                "AUTOMATED_ACCESS",
                "RAW_RETENTION",
                "NORMALIZED_RETENTION",
                "PRIVATE_BACKUP_RESTORE_REPLAY",
                "DERIVED_STATISTICAL_USE",
            }.issubset(operations)
        ):
            raise SourcePolicyError("Current source authorization does not cover this request.")
        self._authorization_limits(entry)
        return entry

    @staticmethod
    def _authorization_limits(entry: Mapping[str, object]) -> dict[str, int]:
        value = entry.get("technical_limits")
        if not isinstance(value, dict):
            raise SourcePolicyError("Current source authorization lacks transport limits.")
        request_limit = value.get("requests")
        byte_limit = value.get("bytes")
        timeout_limit = value.get("timeout_seconds")
        if any(
            type(limit) is not int or limit <= 0
            for limit in (request_limit, byte_limit, timeout_limit)
        ):
            raise SourcePolicyError("Current source authorization has invalid transport limits.")
        if value.get("bypass_access_controls") is not False:
            raise SourcePolicyError("Current source authorization permits access-control bypass.")
        assert isinstance(request_limit, int)
        assert isinstance(byte_limit, int)
        assert isinstance(timeout_limit, int)
        return {
            "requests": request_limit,
            "bytes": byte_limit,
            "timeout_seconds": timeout_limit,
        }

    def _resolve_destination(
        self,
        host: str,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        url: str,
        auth_limits: Mapping[str, int],
    ) -> tuple[str, ...]:
        if self._resolve_public_ips is None:
            timeout = min(
                self.policy.per_request_timeout_seconds,
                self.timeout_seconds,
                float(auth_limits["timeout_seconds"]),
                self._remaining(start),
            )
            if timeout <= 0:
                raise self._budget_failure(
                    url,
                    start,
                    attempts,
                    redirects,
                    "TOTAL_ELAPSED_BUDGET_EXHAUSTED",
                )
            addresses = _resolve_public_source_ips(host, timeout_seconds=timeout)
        else:
            addresses = self._resolve_public_ips(host)
        addresses = _validate_public_ips(addresses)
        self._require_elapsed(start, attempts, redirects, url)
        return addresses

    def _validate_url(self, url: str) -> None:
        try:
            parsed = urlsplit(url)
            hostname = (parsed.hostname or "").casefold().rstrip(".")
            port = parsed.port
        except ValueError as error:
            raise SourcePolicyError(
                "T06 permits only explicitly scoped public HTTPS endpoints."
            ) from error
        path = unquote(parsed.path)
        valid_endpoint = any(
            endpoint.host == hostname and path.startswith(endpoint.path_prefix)
            for endpoint in self.policy.allowed_endpoints
        )
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or "\\" in path
            or path != parsed.path
            or any(segment in {".", ".."} for segment in path.split("/"))
            or hostname in {"localhost", "localhost.localdomain"}
            or hostname.endswith((".localhost", ".local", ".internal", ".test"))
            or not valid_endpoint
        ):
            raise SourcePolicyError("T06 permits only explicitly scoped public HTTPS endpoints.")

    def _require_request_budget(
        self,
        start: float,
        attempts: list[SourceTransportAttempt],
        redirects: list[SourceRedirect],
        url: str,
        request_count: int,
        operation_bytes: int,
        auth_limits: Mapping[str, int],
    ) -> None:
        if request_count >= min(self.policy.max_request_count, auth_limits["requests"]):
            raise self._budget_failure(url, start, attempts, redirects, "REQUEST_BUDGET_EXHAUSTED")
        if operation_bytes >= min(self.policy.max_total_bytes, auth_limits["bytes"]):
            raise self._budget_failure(url, start, attempts, redirects, "BYTE_BUDGET_EXHAUSTED")
        if self.network_requests >= self.policy.max_request_count:
            raise self._budget_failure(url, start, attempts, redirects, "REQUEST_BUDGET_EXHAUSTED")
        if self.network_bytes >= min(self.network_cap_bytes, self.policy.max_total_bytes):
            raise self._budget_failure(url, start, attempts, redirects, "BYTE_BUDGET_EXHAUSTED")

    def _pace(
        self,
        start: float,
        attempts: list[SourceTransportAttempt],
        redirects: list[SourceRedirect],
        url: str,
    ) -> None:
        if self._last_request_started_at is None:
            return
        wait = (
            self._last_request_started_at
            + self.policy.minimum_pacing_interval_seconds
            - self._monotonic()
        )
        if wait > 0:
            self._sleep_with_budget(wait, start, attempts, redirects, url)

    def _sleep_with_budget(
        self,
        delay: float,
        start: float,
        attempts: list[SourceTransportAttempt],
        redirects: list[SourceRedirect],
        url: str,
    ) -> None:
        if delay < 0 or delay >= self._remaining(start):
            raise self._deferred_failure(
                attempts[0].url if attempts else url,
                start,
                attempts,
                redirects,
                "Required provider wait exceeds the remaining transport time budget.",
            )
        if delay:
            self._sleep(delay)
        self._require_elapsed(start, attempts, redirects, url)

    def _retry_delay(self, retry_count: int, retry_after: float | None, start: float) -> float:
        delay = (
            retry_after
            if retry_after is not None
            else min(
                self.policy.base_backoff_seconds * (2**retry_count),
                self.policy.maximum_backoff_seconds,
            )
        )
        if delay > self.policy.maximum_backoff_seconds or delay >= self._remaining(start):
            raise SourceDeferred("Provider Retry-After exceeds the configured remaining budget.")
        return delay

    def _retry_capacity(
        self,
        request_count: int,
        operation_bytes: int,
        auth_limits: Mapping[str, int],
    ) -> bool:
        return (
            request_count < min(self.policy.max_request_count, auth_limits["requests"])
            and self.network_requests < self.policy.max_request_count
            and operation_bytes < min(self.policy.max_total_bytes, auth_limits["bytes"])
            and self.network_bytes < min(self.network_cap_bytes, self.policy.max_total_bytes)
        )

    def _retry_limit_classification(
        self,
        request_count: int,
        operation_bytes: int,
        auth_limits: Mapping[str, int],
    ) -> str:
        if (
            request_count >= min(self.policy.max_request_count, auth_limits["requests"])
            or self.network_requests >= self.policy.max_request_count
        ):
            return "REQUEST_BUDGET_EXHAUSTED"
        if operation_bytes >= min(
            self.policy.max_total_bytes, auth_limits["bytes"]
        ) or self.network_bytes >= min(self.network_cap_bytes, self.policy.max_total_bytes):
            return "BYTE_BUDGET_EXHAUSTED"
        return "REQUEST_BUDGET_EXHAUSTED"

    def _deferred_failure(
        self,
        requested_url: str,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        message: str,
        http_status: int | None = None,
    ) -> SourceDeferred:
        last = attempts[-1] if attempts else None
        provenance = self._provenance(
            requested_url,
            last.url if last else None,
            redirects,
            last.completed_at_utc if last and last.response_status is not None else None,
            http_status if http_status is not None else (last.response_status if last else None),
            last.response_digest if last else None,
            last.bytes_received if last else 0,
            sum(item.bytes_received for item in attempts),
            "DEFERRED",
            sum(item.retry_delay_seconds is not None for item in attempts),
            start,
            attempts,
        )
        return SourceDeferred(
            message,
            http_status=http_status,
            transport_provenance=provenance,
        )

    def _backoff(self, retry_count: int) -> float:
        delay: float = self.policy.base_backoff_seconds * (2**retry_count)
        return (
            self.policy.maximum_backoff_seconds
            if delay > self.policy.maximum_backoff_seconds
            else delay
        )

    def _receive_body(
        self,
        response: SourceHttpResponse,
        *,
        status: int,
        response_headers: Mapping[str, str],
        part_path: Path,
        offset: int,
        start: float,
        operation_bytes: int,
        entry_limits: Mapping[str, int],
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        current_url: str,
        request_deadline: float,
    ) -> tuple[int, int, bool]:
        append = offset > 0 and status == 206
        content_range = response_headers.get("content-range")
        expected_range_bytes: int | None = None
        total_length: int | None = None
        if status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
            if match is None:
                raise SourceIntegrityError("HTTP 206 omitted a valid Content-Range header.")
            range_start, range_end, total_length = map(int, match.groups())
            if range_start != (offset if append else 0) or range_end < range_start:
                raise SourceIntegrityError("HTTP 206 returned an unexpected byte range.")
            expected_range_bytes = range_end - range_start + 1
            if range_end + 1 != total_length:
                raise SourceIntegrityError(
                    "HTTP 206 did not contain the complete remaining source."
                )
        elif offset and status == 200:
            append = False

        content_length_text = response_headers.get("content-length")
        content_length: int | None = None
        if content_length_text is not None:
            try:
                content_length = int(content_length_text)
            except ValueError as error:
                raise SourceIntegrityError(
                    "Source response has an invalid Content-Length."
                ) from error
            if content_length < 0:
                raise SourceIntegrityError("Source response has a negative Content-Length.")
        if expected_range_bytes is not None and content_length not in {None, expected_range_bytes}:
            raise SourceIntegrityError("HTTP 206 Content-Length differs from Content-Range.")
        current_size = offset if append else 0
        byte_count = 0
        if total_length is not None and total_length > self.max_source_bytes:
            raise SourceBudgetExceeded(
                f"Source exceeded the {self.max_source_bytes}-byte limit.",
                failure_classification="SOURCE_BYTE_LIMIT_EXCEEDED",
                http_status=status,
            )
        mode = "ab" if append else "wb"
        with part_path.open(mode) as target:
            os.chmod(part_path, 0o600)
            while True:
                remaining = min(
                    self.max_source_bytes - current_size - byte_count,
                    self.network_cap_bytes - self.network_bytes,
                    self.policy.max_total_bytes - self.network_bytes,
                    self.policy.max_total_bytes - operation_bytes - byte_count,
                    entry_limits["bytes"] - operation_bytes - byte_count,
                )
                if remaining <= 0:
                    if content_length is not None and byte_count == content_length:
                        break
                    raise SourceBudgetExceeded(
                        "Source transport byte budget was exhausted before response completion.",
                        failure_classification="BYTE_BUDGET_EXHAUSTED",
                        http_status=status,
                    )
                self._require_elapsed(start, attempts, redirects, current_url)
                timeout = min(request_deadline - self._monotonic(), self._remaining(start))
                if timeout <= 0:
                    raise TimeoutError("Source response exceeded its per-request timeout.")
                response.set_timeout(timeout)
                chunk = response.read(min(64 * 1024, remaining))
                if not chunk:
                    if self._monotonic() >= request_deadline:
                        raise TimeoutError("Source response exceeded its per-request timeout.")
                    break
                byte_count += len(chunk)
                self.network_bytes += len(chunk)
                target.write(chunk)
                if self._monotonic() >= request_deadline:
                    raise TimeoutError("Source response exceeded its per-request timeout.")
            target.flush()
            os.fsync(target.fileno())
        if content_length is not None and byte_count != content_length:
            raise _IncompleteSourceBody(
                "Source response ended before Content-Length bytes arrived.",
                bytes_received=byte_count,
            )
        if expected_range_bytes is not None and byte_count != expected_range_bytes:
            raise _IncompleteSourceBody(
                "Source response ended before the complete byte range arrived.",
                bytes_received=byte_count,
            )
        if total_length is not None and current_size + byte_count != total_length:
            raise SourceIntegrityError("Source response byte total differs from Content-Range.")
        return current_size + byte_count, byte_count, append

    def _read_response_sample(
        self,
        response: SourceHttpResponse,
        start: float,
        operation_bytes: int,
        entry_limits: Mapping[str, int],
        request_deadline: float,
        max_bytes: int,
    ) -> tuple[bytes, int]:
        available = min(
            max_bytes,
            self.policy.max_total_bytes - self.network_bytes,
            self.network_cap_bytes - self.network_bytes,
            entry_limits["bytes"] - operation_bytes,
        )
        if available <= 0:
            return b"", 0
        timeout = min(
            self.policy.per_request_timeout_seconds,
            self.timeout_seconds,
            float(entry_limits["timeout_seconds"]),
            self._remaining(start),
            request_deadline - self._monotonic(),
        )
        if timeout <= 0:
            raise TimeoutError("Source error response exceeded its per-request timeout.")
        response.set_timeout(timeout)
        sample = response.read(available)
        self.network_bytes += len(sample)
        if self._monotonic() >= request_deadline:
            raise TimeoutError("Source error response exceeded its per-request timeout.")
        return sample, len(sample)

    def _make_attempt(
        self,
        number: int,
        url: str,
        started_at: float,
        started_at_utc: str,
        status: int | None,
        classification: str,
        bytes_received: int,
        *,
        response_digest: str | None = None,
        retry_after_seconds: float | None = None,
        retry_delay_seconds: float | None = None,
    ) -> SourceTransportAttempt:
        return SourceTransportAttempt(
            number,
            url,
            started_at_utc,
            self._utc_text(),
            max(0.0, self._monotonic() - started_at),
            status,
            classification,
            bytes_received,
            response_digest,
            retry_after_seconds,
            retry_delay_seconds,
        )

    @staticmethod
    def _response_digest_from_partial(part_path: Path, byte_count: int) -> str | None:
        if byte_count <= 0 or not part_path.is_file():
            return None
        try:
            partial = part_path.read_bytes()[-byte_count:]
        except OSError:
            return None
        return sha256_bytes(partial)

    def _provenance(
        self,
        requested_url: str,
        final_url: str | None,
        redirects: Sequence[SourceRedirect],
        retrieved_at: str | None,
        status: int | None,
        response_digest: str | None,
        content_byte_count: int,
        network_byte_count: int,
        failure: str | None,
        retries: int,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        *,
        content_digest: str | None = None,
    ) -> SourceTransportProvenance:
        return SourceTransportProvenance(
            requested_url,
            final_url,
            tuple(redirects),
            retrieved_at,
            status,
            response_digest,
            content_digest,
            content_byte_count,
            network_byte_count,
            sum(not item.classification.startswith("DNS_") for item in attempts),
            failure,
            retries,
            max(0.0, self._monotonic() - start),
            tuple(attempts),
        )

    def _refused(
        self,
        url: str,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        message: str,
        classification: str,
        *,
        http_status: int | None = None,
    ) -> SourceRefused:
        last = attempts[-1] if attempts else None
        provenance = self._provenance(
            url,
            last.url if last else None,
            redirects,
            last.completed_at_utc if last and last.response_status is not None else None,
            http_status if http_status is not None else (last.response_status if last else None),
            last.response_digest if last else None,
            last.bytes_received if last else 0,
            sum(item.bytes_received for item in attempts),
            classification,
            sum(item.retry_delay_seconds is not None for item in attempts),
            start,
            attempts,
        )
        return SourceRefused(
            message,
            http_status=http_status,
            failure_classification=classification,
            transport_provenance=provenance,
        )

    def _unavailable(
        self,
        url: str,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        message: str,
        classification: str,
        *,
        http_status: int | None = None,
    ) -> SourceUnavailable:
        last = attempts[-1] if attempts else None
        provenance = self._provenance(
            url,
            last.url if last else None,
            redirects,
            last.completed_at_utc if last and last.response_status is not None else None,
            http_status if http_status is not None else (last.response_status if last else None),
            last.response_digest if last else None,
            last.bytes_received if last else 0,
            sum(item.bytes_received for item in attempts),
            classification,
            sum(item.retry_delay_seconds is not None for item in attempts),
            start,
            attempts,
        )
        return SourceUnavailable(
            message,
            http_status=http_status,
            failure_classification=classification,
            transport_provenance=provenance,
        )

    def _budget_failure(
        self,
        url: str,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        classification: str,
        http_status: int | None = None,
    ) -> SourceBudgetExceeded:
        last = attempts[-1] if attempts else None
        provenance = self._provenance(
            url,
            last.url if last else None,
            redirects,
            last.completed_at_utc if last and last.response_status is not None else None,
            http_status if http_status is not None else (last.response_status if last else None),
            last.response_digest if last else None,
            last.bytes_received if last else 0,
            sum(item.bytes_received for item in attempts),
            classification,
            sum(item.retry_delay_seconds is not None for item in attempts),
            start,
            attempts,
        )
        return SourceBudgetExceeded(
            "Public source transport reached a configured bound.",
            http_status=http_status,
            failure_classification=classification,
            transport_provenance=provenance,
        )

    def _require_elapsed(
        self,
        start: float,
        attempts: Sequence[SourceTransportAttempt],
        redirects: Sequence[SourceRedirect],
        url: str,
    ) -> None:
        if self._remaining(start) <= 0:
            raise self._budget_failure(
                url, start, attempts, redirects, "TOTAL_ELAPSED_BUDGET_EXHAUSTED"
            )

    def _remaining(self, start: float) -> float:
        return self.policy.total_elapsed_budget_seconds - (self._monotonic() - start)

    def _utc_text(self) -> str:
        value = self._utcnow()
        if value.utcoffset() is None:
            raise ValueError("Transport wall clock must return an aware datetime.")
        return value.astimezone(UTC).isoformat()

    def _discard_partial(self, part_path: Path) -> None:
        with contextlib.suppress(FileNotFoundError):
            part_path.unlink()

    def _cache_size(self) -> int:
        try:
            return sum(path.stat().st_size for path in self.cache_root.iterdir() if path.is_file())
        except OSError:
            return self.cache_storage_cap_bytes

    def _write_cache_metadata(self, meta_path: Path, metadata: Mapping[str, object]) -> None:
        raw = _canonical_json(dict(metadata))
        meta_tmp = meta_path.with_suffix(".tmp")
        meta_tmp.write_bytes(raw)
        os.chmod(meta_tmp, 0o600)
        descriptor = os.open(meta_tmp, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(meta_tmp, meta_path)


@dataclass(frozen=True)
class IngestionPlan:
    current_season: str
    historical_seasons: tuple[str, ...] = ()
    leagues: tuple[LeagueConfig, ...] = TARGET_LEAGUES
    use_openfootball_fallback: bool = True
    refresh_current: bool = False
    matchweek_friday: str | None = None

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
        if self.matchweek_friday is not None:
            from matchvet.matchweek import MatchweekWindow

            window = MatchweekWindow.for_friday(self.matchweek_friday)
            if window.friday_local.isoformat() != self.matchweek_friday:
                raise ValueError("Matchweek Friday must use YYYY-MM-DD.")

    @property
    def seasons(self) -> tuple[str, ...]:
        return (self.current_season, *self.historical_seasons)

    @property
    def plan_digest(self) -> str:
        payload: dict[str, object] = {
            "current_season": self.current_season,
            "historical_seasons": self.historical_seasons,
            "leagues": [league.key for league in self.leagues],
            "refresh_current": self.refresh_current,
            "source_policy": "t06-source-policy-v1",
            "use_openfootball_fallback": self.use_openfootball_fallback,
        }
        if self.matchweek_friday is not None:
            payload["matchweek_friday"] = self.matchweek_friday
            payload["scheduled_fixture_capability"] = "openfootball-json-and-text-schedule-v1"
        return sha256_bytes(_canonical_json(payload))

    @property
    def run_key(self) -> str:
        return f"t06-fixture-history:{self.plan_digest}"

    @property
    def expected_network_bytes(self) -> int:
        expected = len(self.seasons) * len(self.leagues) * 2 * 1024 * 1024
        if self.matchweek_friday is not None:
            supported_count = sum(league.openfootball_supported for league in self.leagues)
            expected += supported_count * 4 * 1024 * 1024
        return max(1, expected)


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
    scheduled_fixtures: ScheduledFixtureAcquisition | None = None

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


@dataclass(frozen=True)
class ScheduledFixtureAcquisition:
    imports: tuple[ImportResult, ...]
    diagnostics: tuple[str, ...]
    assessment: FixtureCoverageAssessment
    bytes_downloaded: int
    cache_hits: int


class FixtureHistoryAcquirer:
    """Acquire primary files and permitted fallback files for an IngestionPlan."""

    def __init__(
        self,
        importer: FixtureHistoryImporter,
        fetcher: SourceFetcher,
        *,
        attempted_at: Callable[[], str] = _utc_now_text,
    ) -> None:
        self.importer = importer
        self.fetcher = fetcher
        self.attempted_at = attempted_at
        self.football_data_parser = FootballDataCSVParser()
        self.openfootball_parser = OpenFootballJSONParser()
        self.openfootball_text_parser = OpenFootballTextParser()

    def acquire(self, plan: IngestionPlan) -> AcquisitionReport:
        configure = getattr(self.fetcher, "configure_for_plan", None)
        if callable(configure):
            configure(historical=bool(plan.historical_seasons))
        imports: list[ImportResult] = []
        issues: list[AcquisitionIssue] = []
        bytes_downloaded = 0
        cache_hits = 0
        fallback_imports = 0
        deferred_current_fallbacks: list[tuple[LeagueConfig, str, SourceUnavailable]] = []
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
                    if primary_error.terminal:
                        raise
                    if (
                        plan.matchweek_friday is not None
                        and season == plan.current_season
                        and plan.use_openfootball_fallback
                        and league.openfootball_supported
                    ):
                        deferred_current_fallbacks.append((league, primary_url, primary_error))
                        continue
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
                        if fallback_error.terminal:
                            raise
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
                            transport_provenance=downloaded.transport_provenance,
                        ),
                        scheduled_rows_known_only=season == plan.current_season,
                    )
                    imports.append(result)
                    fallback_imports += 1
                    bytes_downloaded += downloaded.bytes_downloaded
                    cache_hits += int(downloaded.from_cache)
                    continue
                try:
                    dataset = self.football_data_parser.parse(
                        downloaded.content, league=league, season=season
                    )
                except SourceParseError as error:
                    if plan.matchweek_friday is None:
                        raise
                    issues.append(
                        AcquisitionIssue(
                            SourceKind.FOOTBALL_DATA,
                            league.key,
                            season,
                            primary_url,
                            str(error),
                            False,
                        )
                    )
                    bytes_downloaded += downloaded.bytes_downloaded
                    cache_hits += int(downloaded.from_cache)
                    continue
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
                        transport_provenance=downloaded.transport_provenance,
                    ),
                    scheduled_rows_known_only=season == plan.current_season,
                )
                imports.append(result)
                bytes_downloaded += downloaded.bytes_downloaded
                cache_hits += int(downloaded.from_cache)
        scheduled_fixtures: ScheduledFixtureAcquisition | None = None
        current_fallback_imports: dict[str, ImportResult] = {}
        current_fallback_downloads: dict[str, DownloadedSource] = {}
        if plan.matchweek_friday is not None:
            for league, _primary_url, result_source_error in deferred_current_fallbacks:
                fallback_url = openfootball_url(league, plan.current_season)
                try:
                    downloaded_fallback = self.fetcher.fetch(
                        fallback_url,
                        cache_key=f"openfootball:{league.key}:{plan.current_season}",
                        refresh=plan.refresh_current,
                    )
                except SourceUnavailable as fallback_error:
                    if fallback_error.terminal:
                        raise
                    issues.append(
                        AcquisitionIssue(
                            SourceKind.OPENFOOTBALL,
                            league.key,
                            plan.current_season,
                            fallback_url,
                            f"{result_source_error}; {fallback_error}",
                            True,
                        )
                    )
                    continue
                bytes_downloaded += downloaded_fallback.bytes_downloaded
                cache_hits += int(downloaded_fallback.from_cache)
                try:
                    dataset = self.openfootball_parser.parse(
                        downloaded_fallback.content,
                        league=league,
                        season=plan.current_season,
                    )
                except SourceParseError as error:
                    issues.append(
                        AcquisitionIssue(
                            SourceKind.OPENFOOTBALL,
                            league.key,
                            plan.current_season,
                            fallback_url,
                            str(error),
                            True,
                        )
                    )
                    continue
                result = self.importer.import_dataset(
                    dataset,
                    downloaded_fallback.content,
                    SourceCaptureInput(
                        source_url=fallback_url,
                        retrieved_at_utc=downloaded_fallback.retrieved_at_utc,
                        response_status=downloaded_fallback.response_status,
                        content_type=downloaded_fallback.content_type,
                        observed_terms="OpenFootball CC0",
                        cache_key=f"openfootball:{league.key}:{plan.current_season}",
                        transport_provenance=downloaded_fallback.transport_provenance,
                    ),
                    scheduled_rows_known_only=True,
                )
                imports.append(result)
                fallback_imports += 1
                current_fallback_imports[league.key] = result
                current_fallback_downloads[league.key] = downloaded_fallback
            scheduled_fixtures, _scheduled_downloads = self._acquire_scheduled_fixtures(
                plan,
                existing_json_captures=current_fallback_imports,
                existing_json_downloads=current_fallback_downloads,
            )
        return AcquisitionReport(
            plan.plan_digest,
            tuple(imports),
            tuple(issues),
            bytes_downloaded,
            cache_hits,
            fallback_imports,
            scheduled_fixtures,
        )

    def acquire_scheduled_fixtures(self, plan: IngestionPlan) -> ScheduledFixtureAcquisition:
        """Acquire and assess the requested Matchweek's independent schedule feeds."""
        if plan.matchweek_friday is None:
            raise ValueError("Scheduled fixture acquisition requires matchweek_friday.")
        configure = getattr(self.fetcher, "configure_for_plan", None)
        if callable(configure):
            configure(historical=bool(plan.historical_seasons))
        scheduled, _downloads = self._acquire_scheduled_fixtures(plan)
        return scheduled

    def _capture_scheduled_feed(
        self,
        *,
        plan: IngestionPlan,
        league: LeagueConfig,
        scope_id: str,
        source_url: str,
        cache_key: str,
        provider_id: str,
        source_kind: SourceKind,
        parser: OpenFootballJSONParser | OpenFootballTextParser,
        reused_capture: ImportResult | None = None,
        reused_download: DownloadedSource | None = None,
    ) -> tuple[
        ProviderAttempt, ImportResult | None, DownloadedSource | None, str | None, tuple[str, ...]
    ]:
        from matchvet.fixture_coverage import ProviderAttemptState

        try:
            downloaded = reused_download or self.fetcher.fetch(
                source_url, cache_key=cache_key, refresh=plan.refresh_current
            )
        except SourceUnavailable as error:
            if error.terminal:
                raise
            attempt = _scheduled_provider_attempt(
                scope_id=scope_id,
                provider_id=provider_id,
                state=ProviderAttemptState.UNAVAILABLE,
                attempted_at_utc=_canonical_f01_utc(self.attempted_at()),
                http_status=error.http_status,
                capture_id=None,
                capture_digest=None,
            )
            return attempt, None, None, str(error), ()

        capture = SourceCaptureInput(
            source_url=source_url,
            retrieved_at_utc=downloaded.retrieved_at_utc,
            response_status=downloaded.response_status,
            content_type=downloaded.content_type,
            observed_terms="OpenFootball CC0",
            cache_key=cache_key,
            transport_provenance=downloaded.transport_provenance,
        )
        try:
            dataset = parser.parse(downloaded.content, league=league, season=plan.current_season)
        except SourceParseError as error:
            retained = self.importer.retain_capture(
                source_kind=source_kind,
                league=league,
                season=plan.current_season,
                content=downloaded.content,
                capture=capture,
            )
            attempt = _scheduled_provider_attempt(
                scope_id=scope_id,
                provider_id=provider_id,
                state=ProviderAttemptState.MALFORMED,
                attempted_at_utc=_canonical_f01_utc(downloaded.retrieved_at_utc),
                http_status=downloaded.response_status,
                capture_id=retained.capture_id,
                capture_digest=retained.content_sha256,
            )
            return attempt, None, downloaded, str(error), ()

        scheduled_dataset = replace(
            dataset,
            rows=tuple(row for row in dataset.rows if _fixture_status(row) != "COMPLETED"),
        )
        if reused_capture is None:
            result = self.importer.import_dataset(
                scheduled_dataset,
                downloaded.content,
                capture,
                identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
            )
        else:
            result = replace(
                reused_capture,
                fixtures_seen=len(scheduled_dataset.rows),
                fixtures_imported=0,
                revisions_appended=0,
                statistics_imported=0,
                unknown_fields=0,
                duplicate_rows=len(scheduled_dataset.rows),
                unresolved_rows=0,
                from_existing_capture=True,
            )
        attempt = _scheduled_provider_attempt(
            scope_id=scope_id,
            provider_id=provider_id,
            state=ProviderAttemptState.CAPTURED,
            attempted_at_utc=_canonical_f01_utc(downloaded.retrieved_at_utc),
            http_status=downloaded.response_status,
            capture_id=result.source_capture_id,
            capture_digest=result.source_digest,
        )
        return (
            attempt,
            result,
            downloaded,
            None,
            tuple(row.source_row_key for row in scheduled_dataset.rows),
        )

    def _acquire_scheduled_fixtures(
        self,
        plan: IngestionPlan,
        *,
        existing_json_captures: Mapping[str, ImportResult] | None = None,
        existing_json_downloads: Mapping[str, DownloadedSource] | None = None,
    ) -> tuple[ScheduledFixtureAcquisition, dict[str, DownloadedSource]]:
        from matchvet.fixture_coverage import (
            FixtureIdentityResolution,
            FixtureIdentityState,
            FixtureRevisionReference,
            ProviderAttemptState,
            assess_fixture_coverage,
            fixture_scopes_for_matchweek,
        )
        from matchvet.matchweek import MatchweekWindow

        assert plan.matchweek_friday is not None
        scopes = fixture_scopes_for_matchweek(plan.matchweek_friday, season=plan.current_season)
        scopes_by_league = {scope.league_key: scope for scope in scopes}
        attempts: list[ProviderAttempt] = []
        imports: list[ImportResult] = []
        diagnostics = ["belgian_pro_league: no approved schedule source configured"]
        attempt_diagnostics: dict[str, str] = {}
        downloads: dict[str, DownloadedSource] = {}
        capture_scopes: dict[str, str] = {}
        capture_rows: dict[str, set[str]] = {}
        bytes_downloaded = 0
        cache_hits = 0

        for league in plan.leagues:
            if not league.openfootball_supported:
                continue
            scope = scopes_by_league[league.key]
            feed_specs = (
                (
                    openfootball_url(league, plan.current_season),
                    f"openfootball-schedule-json:{league.key}:{plan.current_season}",
                    "openfootball-json",
                    SourceKind.OPENFOOTBALL,
                    self.openfootball_parser,
                ),
                (
                    openfootball_text_url(league, plan.current_season),
                    f"openfootball-schedule-text:{league.key}:{plan.current_season}",
                    "openfootball-footballtxt",
                    SourceKind.OPENFOOTBALL_TEXT,
                    self.openfootball_text_parser,
                ),
            )
            for source_url, cache_key, provider_id, source_kind, source_parser in feed_specs:
                attempt, result, downloaded, diagnostic, row_keys = self._capture_scheduled_feed(
                    plan=plan,
                    league=league,
                    scope_id=scope.scope_id,
                    source_url=source_url,
                    cache_key=cache_key,
                    provider_id=provider_id,
                    source_kind=source_kind,
                    parser=source_parser,
                    reused_capture=(
                        existing_json_captures.get(league.key)
                        if existing_json_captures is not None
                        and source_kind is SourceKind.OPENFOOTBALL
                        else None
                    ),
                    reused_download=(
                        existing_json_downloads.get(league.key)
                        if existing_json_downloads is not None
                        and source_kind is SourceKind.OPENFOOTBALL
                        else None
                    ),
                )
                attempts.append(attempt)
                if downloaded is not None:
                    bytes_downloaded += downloaded.bytes_downloaded
                    cache_hits += int(downloaded.from_cache)
                    if provider_id == "openfootball-json":
                        downloads[league.key] = downloaded
                if attempt.capture_id is not None:
                    capture_scopes[attempt.capture_id] = scope.scope_id
                    capture_rows[attempt.capture_id] = set(row_keys)
                if result is not None:
                    imports.append(result)
                if diagnostic is not None:
                    attempt_diagnostics[attempt.attempt_id] = diagnostic
                    kind = (
                        "unavailable"
                        if attempt.state is ProviderAttemptState.UNAVAILABLE
                        else "malformed"
                    )
                    diagnostics.append(f"{league.key}: {provider_id} {kind}: {diagnostic}")

        from matchvet.operator_fixture_observation import OperatorFixtureObservationRepository

        manual_repository = OperatorFixtureObservationRepository(
            self.importer._store,
            private_root=self.importer._private_root,
        )
        for manual_scope in scopes:
            for manual_record in manual_repository.list_for_scope(manual_scope.scope_id):
                capture_id = manual_record.capture_id
                row_key = f"official-observation:{manual_record.observation.digest}"
                capture_scopes[capture_id] = manual_scope.scope_id
                capture_rows[capture_id] = {row_key}
                imports.append(manual_record.import_result)

        window = MatchweekWindow.for_friday(plan.matchweek_friday)
        revisions_by_id: dict[str, FixtureRevisionReference] = {}
        fixture_revisions: dict[tuple[str, str], set[str]] = {}
        fixture_assertions: dict[tuple[str, str], set[str]] = {}
        unresolved_identities: list[FixtureIdentityResolution] = []
        for capture_id, scope_id in capture_scopes.items():
            scope = next(scope for scope in scopes if scope.scope_id == scope_id)
            scope_start_utc = datetime.fromisoformat(scope.window_start_utc)
            scope_end_utc = datetime.fromisoformat(scope.window_end_utc)
            league = _LEAGUES_BY_KEY[scope.league_key]
            for observation in self.importer.observations_for_capture(capture_id):
                if observation.source_row_key not in capture_rows[capture_id]:
                    continue
                if observation.kickoff_utc is not None:
                    in_scope = window.contains(observation.kickoff_utc)
                elif observation.kickoff_local_date is not None:
                    local_date = observation.kickoff_local_date
                    day_start_utc = datetime.combine(
                        local_date, time.min, _source_timezone(league.timezone, local_date)
                    ).astimezone(UTC)
                    following_date = local_date + timedelta(days=1)
                    day_end_utc = datetime.combine(
                        following_date,
                        time.min,
                        _source_timezone(league.timezone, following_date),
                    ).astimezone(UTC)
                    # An unknown kickoff is assignable only when its whole local day fits F01's
                    # window. A boundary overlap leaves scope membership uncertain.
                    in_scope = day_start_utc >= scope_start_utc and day_end_utc <= scope_end_utc
                else:
                    in_scope = False
                if not in_scope:
                    continue
                if observation.fixture_id is None:
                    unresolved_identities.append(
                        FixtureIdentityResolution(
                            candidate_id=deterministic_identifier(
                                "fixture_candidate", f"{capture_id}:{observation.source_row_key}"
                            ),
                            scope_id=scope.scope_id,
                            state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
                            reason_code=observation.reason_code or "TEAM_MAPPING_UNRESOLVED",
                            source_capture_ids=(capture_id,),
                            source_assertion_ids=observation.source_assertion_ids,
                        )
                    )
                    continue
                assert observation.revision_id is not None
                assert observation.revision_digest is not None
                reference = FixtureRevisionReference(
                    scope_id=scope.scope_id,
                    fixture_id=observation.fixture_id,
                    revision_id=observation.revision_id,
                    revision_digest=observation.revision_digest,
                    source_capture_ids=(capture_id,),
                    source_assertion_ids=observation.source_assertion_ids,
                )
                existing_reference = revisions_by_id.get(observation.revision_id)
                if existing_reference is not None:
                    reference = FixtureRevisionReference(
                        scope_id=scope.scope_id,
                        fixture_id=observation.fixture_id,
                        revision_id=observation.revision_id,
                        revision_digest=observation.revision_digest,
                        source_capture_ids=tuple(
                            sorted(set(existing_reference.source_capture_ids) | {capture_id})
                        ),
                        source_assertion_ids=tuple(
                            sorted(
                                set(existing_reference.source_assertion_ids)
                                | set(observation.source_assertion_ids)
                            )
                        ),
                    )
                revisions_by_id[observation.revision_id] = reference
                fixture_key = (scope.scope_id, observation.fixture_id)
                fixture_revisions.setdefault(fixture_key, set()).add(observation.revision_id)
                fixture_assertions.setdefault(fixture_key, set()).update(
                    observation.source_assertion_ids
                )

        resolved_identities = [
            FixtureIdentityResolution(
                candidate_id=deterministic_identifier(
                    "fixture_candidate", f"{scope_id}:{fixture_id}"
                ),
                scope_id=scope_id,
                state=FixtureIdentityState.RESOLVED,
                canonical_fixture_id=fixture_id,
                revision_ids=tuple(sorted(revision_ids)),
                source_capture_ids=tuple(
                    sorted(
                        {
                            capture_id
                            for revision_id in revision_ids
                            for capture_id in revisions_by_id[revision_id].source_capture_ids
                        }
                    )
                ),
                source_assertion_ids=tuple(sorted(fixture_assertions[(scope_id, fixture_id)])),
            )
            for (scope_id, fixture_id), revision_ids in fixture_revisions.items()
        ]
        assessment = assess_fixture_coverage(
            scopes=scopes,
            provider_attempts=tuple(attempts),
            coverage_evidence=(),
            fixture_revisions=tuple(revisions_by_id.values()),
            identity_resolutions=tuple(resolved_identities + unresolved_identities),
            freshness_results=(),
        )
        from matchvet.fixture_coverage_repository import (
            FixtureCoveragePersistenceError,
            FixtureCoverageRepository,
        )

        try:
            FixtureCoverageRepository(self.importer._store).persist(assessment)
        except Exception as error:
            raise FixtureCoveragePersistenceError(
                "The F01 Fixture Coverage Assessment could not be persisted."
            ) from error
        from matchvet.provider_health_acquisition import build_provider_health_records
        from matchvet.provider_health_repository import (
            ProviderHealthPersistenceError,
            ProviderHealthRepository,
        )

        try:
            health_records = build_provider_health_records(
                assessment, attempt_diagnostics=attempt_diagnostics
            )
            ProviderHealthRepository(self.importer._store).persist_many(health_records)
        except Exception as error:
            raise ProviderHealthPersistenceError(
                "The F04 Provider Health Record batch could not be persisted."
            ) from error
        return (
            ScheduledFixtureAcquisition(
                imports=tuple(imports),
                diagnostics=tuple(diagnostics),
                assessment=assessment,
                bytes_downloaded=bytes_downloaded,
                cache_hits=cache_hits,
            ),
            downloads,
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

"""T19 research-only software release qualification.

This module composes and records existing MatchVet contracts. It never
promotes a Selection Policy and never creates a production match decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from matchvet.ingestion import TARGET_LEAGUES
from matchvet.runs import GIB, SETTLED_RESOURCE_BUDGET, observe_resources

if TYPE_CHECKING:
    from matchvet.ingestion import AcquisitionReport
    from matchvet.matchweek import MatchweekFreeze
    from matchvet.store import Store
    from matchvet.t08 import T08Evidence
    from matchvet.t09 import FrozenEvidenceState, TargetMatch

T19_CORPUS_SCHEMA = "matchvet.recorded-qualification-corpus.v1"
T19_QUALIFICATION_SCHEMA = "matchvet.research-only-release-qualification.v1"
_TEMPORARY_STORAGE_LIMIT_BYTES = 2 * GIB

REQUIRED_QUALIFICATION_GATES = (
    "static_checks",
    "default_tests",
    "migrations_recovery",
    "cli_report_audit_export_backup_restore",
    "seven_league_recorded_e2e",
    "deterministic_replay",
    "offline_rebuild_install",
    "termux_smoke",
    "resource_benchmark",
    "chronological_evaluation",
    "failure_injection",
)


class T19Error(Exception):
    """Base class for release-qualification failures."""


class T19ValidationError(T19Error):
    """An external corpus or evidence record violates the T19 contract."""


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class QualificationStatus(StrEnum):
    QUALIFIED_RESEARCH_ONLY = "QUALIFIED_RESEARCH_ONLY"
    NOT_QUALIFIED = "NOT_QUALIFIED"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _prohibited_market_keys(value: object, path: str = "") -> tuple[str, ...]:
    prohibited = {"bookmaker", "odds", "price", "profit", "roi", "stake", "volume"}
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            selected = f"{path}.{key}" if path else str(key)
            if str(key).casefold() in prohibited:
                found.append(selected)
            found.extend(_prohibited_market_keys(item, selected))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_prohibited_market_keys(item, f"{path}[{index}]"))
    return tuple(found)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T19ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _utc_text(value: object, label: str) -> str:
    selected = _text(value, label)
    try:
        instant = datetime.fromisoformat(selected)
    except ValueError as error:
        raise T19ValidationError(f"{label} must be an ISO-8601 UTC timestamp.") from error
    if instant.utcoffset() != timedelta(0):
        raise T19ValidationError(f"{label} must be an ISO-8601 UTC timestamp.")
    return instant.isoformat()


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise T19ValidationError(f"{label} must be a boolean.")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise T19ValidationError(f"{label} must be a nonnegative integer.")
    return value


def _sha256(value: str, label: str) -> str:
    if len(value) != 64:
        raise T19ValidationError(f"{label} must be a SHA-256 digest.")
    try:
        int(value, 16)
    except ValueError as error:
        raise T19ValidationError(f"{label} must be a SHA-256 digest.") from error
    return value.lower()


def _git_id(value: str, label: str) -> str:
    if len(value) != 40:
        raise T19ValidationError(f"{label} must be a 40-character Git ID.")
    try:
        int(value, 16)
    except ValueError as error:
        raise T19ValidationError(f"{label} must be hexadecimal.") from error
    return value.lower()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise T19ValidationError(f"{label} must be an object with string keys.")
    return cast(dict[str, object], value)


def _require_exact_keys(value: dict[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise T19ValidationError(
            f"{label} fields must match the schema exactly; missing={missing}, extra={extra}."
        )


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise T19ValidationError(f"{label} must be an array.")
    return value


@dataclass(frozen=True)
class CorpusRights:
    classification: str
    license: str
    redistributable: bool
    contains_third_party_raw_data: bool

    @classmethod
    def from_value(cls, value: object) -> CorpusRights:
        raw = _mapping(value, "Corpus rights")
        _require_exact_keys(
            raw,
            {
                "classification",
                "contains_third_party_raw_data",
                "license",
                "redistributable",
            },
            "Corpus rights",
        )
        result = cls(
            classification=_text(raw.get("classification"), "Rights classification"),
            license=_text(raw.get("license"), "Rights license"),
            redistributable=_bool(raw.get("redistributable"), "Rights redistributable"),
            contains_third_party_raw_data=_bool(
                raw.get("contains_third_party_raw_data"),
                "Rights third-party raw-data flag",
            ),
        )
        if not result.redistributable:
            raise T19ValidationError("The recorded qualification corpus must be redistributable.")
        if result.contains_third_party_raw_data:
            raise T19ValidationError(
                "The recorded qualification corpus cannot contain third-party raw data."
            )
        if result.classification != "SELF_AUTHORED_STRUCTURAL_EQUIVALENT":
            raise T19ValidationError(
                "The recorded qualification corpus must be a self-authored structural equivalent."
            )
        if result.license != "CC0-1.0":
            raise T19ValidationError("The recorded qualification corpus must use CC0-1.0.")
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "contains_third_party_raw_data": self.contains_third_party_raw_data,
            "license": self.license,
            "redistributable": self.redistributable,
        }


RecordedCount = int | None
RecordedResult = tuple[
    RecordedCount,
    RecordedCount,
    RecordedCount,
    RecordedCount,
    RecordedCount,
    RecordedCount,
]


def _recorded_result(value: object, label: str) -> RecordedResult:
    row = _sequence(value, label)
    if len(row) != 6:
        raise T19ValidationError(f"{label} must contain six goal and corner values.")
    parsed: list[RecordedCount] = []
    for index, item in enumerate(row):
        if item is None:
            parsed.append(None)
        else:
            parsed.append(_nonnegative_int(item, f"{label}[{index}]"))
    return cast(RecordedResult, tuple(parsed))


@dataclass(frozen=True)
class RecordedLeaguePack:
    league_key: str
    source_mode: str
    team_prefix: str
    target_date: str
    target_time: str
    history_results: tuple[RecordedResult, ...]
    settlement: RecordedResult

    @classmethod
    def from_value(cls, value: object) -> RecordedLeaguePack:
        raw = _mapping(value, "Recorded league pack")
        _require_exact_keys(
            raw,
            {
                "history_results",
                "league_key",
                "settlement",
                "source_mode",
                "target_date",
                "target_time",
                "team_prefix",
            },
            "Recorded league pack",
        )
        source_mode = _text(raw.get("source_mode"), "Source mode")
        if source_mode not in {"FOOTBALL_DATA", "OPENFOOTBALL_FALLBACK"}:
            raise T19ValidationError(f"Unsupported recorded source mode: {source_mode}.")
        history = tuple(
            _recorded_result(item, "Historical result")
            for item in _sequence(raw.get("history_results"), "Historical results")
        )
        if len(history) != 6:
            raise T19ValidationError(
                "Each recorded league pack requires exactly six historical results."
            )
        target_date = _text(raw.get("target_date"), "Target date")
        target_time = _text(raw.get("target_time"), "Target time")
        try:
            datetime.strptime(f"{target_date} {target_time}", "%d/%m/%Y %H:%M")
        except ValueError as error:
            raise T19ValidationError("Recorded target date/time is invalid.") from error
        return cls(
            league_key=_text(raw.get("league_key"), "League key"),
            source_mode=source_mode,
            team_prefix=_text(raw.get("team_prefix"), "Team prefix"),
            target_date=target_date,
            target_time=target_time,
            history_results=history,
            settlement=_recorded_result(raw.get("settlement"), "Settlement"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "history_results": self.history_results,
            "league_key": self.league_key,
            "settlement": self.settlement,
            "source_mode": self.source_mode,
            "target_date": self.target_date,
            "target_time": self.target_time,
            "team_prefix": self.team_prefix,
        }


@dataclass(frozen=True)
class RecordedCorpus:
    season: str
    matchweek_friday: str
    captured_at_utc: str
    rights: CorpusRights
    scenarios: MappingProxyType[str, str]
    leagues: tuple[RecordedLeaguePack, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        expected_keys = tuple(league.key for league in TARGET_LEAGUES)
        actual_keys = tuple(pack.league_key for pack in self.leagues)
        if actual_keys != expected_keys:
            raise T19ValidationError(
                "The recorded corpus must cover the exact seven-league Target League Set in order."
            )
        if len(set(actual_keys)) != len(actual_keys):
            raise T19ValidationError("Recorded league keys must be unique.")
        if len({pack.team_prefix.casefold() for pack in self.leagues}) != len(self.leagues):
            raise T19ValidationError("Recorded team prefixes must be unique across league packs.")
        try:
            friday = datetime.strptime(self.matchweek_friday, "%Y-%m-%d").date()
        except ValueError as error:
            raise T19ValidationError("Recorded Matchweek Friday is invalid.") from error
        if friday.weekday() != 4:
            raise T19ValidationError("Recorded Matchweek date must be a Friday.")
        known_keys = set(actual_keys)
        for name, league_key in self.scenarios.items():
            if league_key not in known_keys:
                raise T19ValidationError(f"Scenario {name} names an unknown league.")
        expected = _digest(self._payload())
        if self.digest and self.digest != expected:
            raise T19ValidationError("Recorded corpus digest does not match its content.")
        object.__setattr__(self, "digest", expected)

    @property
    def league_keys(self) -> tuple[str, ...]:
        return tuple(pack.league_key for pack in self.leagues)

    @classmethod
    def read(cls, path: Path) -> RecordedCorpus:
        try:
            return cls.from_bytes(path.read_bytes())
        except OSError as error:
            raise T19ValidationError(f"Cannot read recorded corpus: {error}") from error

    @classmethod
    def from_bytes(cls, content: bytes) -> RecordedCorpus:
        try:
            loaded: object = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T19ValidationError("Recorded corpus JSON is malformed.") from error
        raw = _mapping(loaded, "Recorded corpus")
        _require_exact_keys(
            raw,
            {
                "captured_at_utc",
                "leagues",
                "matchweek_friday",
                "rights",
                "scenarios",
                "schema",
                "season",
            },
            "Recorded corpus",
        )
        if raw.get("schema") != T19_CORPUS_SCHEMA:
            raise T19ValidationError("Recorded corpus schema is unsupported.")
        scenario_raw = _mapping(raw.get("scenarios"), "Recorded scenarios")
        _require_exact_keys(
            scenario_raw,
            {
                "conflict_league",
                "fallback_league",
                "missing_corners_league",
                "unknown_context_league",
                "withdrawn_league",
            },
            "Recorded scenarios",
        )
        scenarios = {
            _text(key, "Scenario name"): _text(value, f"Scenario {key}")
            for key, value in scenario_raw.items()
        }
        return cls(
            season=_text(raw.get("season"), "Season"),
            matchweek_friday=_text(raw.get("matchweek_friday"), "Matchweek Friday"),
            captured_at_utc=_utc_text(raw.get("captured_at_utc"), "Capture time"),
            rights=CorpusRights.from_value(raw.get("rights")),
            scenarios=MappingProxyType(dict(sorted(scenarios.items()))),
            leagues=tuple(
                RecordedLeaguePack.from_value(item)
                for item in _sequence(raw.get("leagues"), "Recorded leagues")
            ),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "captured_at_utc": self.captured_at_utc,
            "leagues": [pack.to_dict() for pack in self.leagues],
            "matchweek_friday": self.matchweek_friday,
            "rights": self.rights.to_dict(),
            "scenarios": dict(self.scenarios),
            "schema": T19_CORPUS_SCHEMA,
            "season": self.season,
        }

    def to_bytes(self) -> bytes:
        return _canonical_json(self._payload())


@dataclass(frozen=True)
class GateEvidence:
    name: str
    status: GateStatus
    command: str
    exit_code: int
    output_digest: str
    elapsed_seconds: float | None = None
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "Gate name"))
        object.__setattr__(self, "status", GateStatus(self.status))
        object.__setattr__(self, "command", _text(self.command, "Gate command"))
        if not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool):
            raise T19ValidationError("Gate exit code must be an integer.")
        object.__setattr__(self, "output_digest", _sha256(self.output_digest, "Gate output"))
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise T19ValidationError("Gate elapsed seconds cannot be negative.")

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "details": self.details,
            "elapsed_seconds": self.elapsed_seconds,
            "exit_code": self.exit_code,
            "name": self.name,
            "output_digest": self.output_digest,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class ResourceMeasurement:
    runtime_seconds: float
    peak_memory_bytes: int | None
    temporary_storage_growth_bytes: int
    final_managed_storage_bytes: int
    free_space_floor_bytes: int
    cpu_heavy_concurrency: int
    network_bytes: int

    def __post_init__(self) -> None:
        if self.runtime_seconds < 0:
            raise T19ValidationError("Measured runtime cannot be negative.")
        if self.peak_memory_bytes is not None and self.peak_memory_bytes < 0:
            raise T19ValidationError("Measured peak memory cannot be negative.")
        for name in (
            "temporary_storage_growth_bytes",
            "final_managed_storage_bytes",
            "free_space_floor_bytes",
            "cpu_heavy_concurrency",
            "network_bytes",
        ):
            if getattr(self, name) < 0:
                raise T19ValidationError(f"Measured {name} cannot be negative.")

    def failures(self) -> tuple[str, ...]:
        budget = SETTLED_RESOURCE_BUDGET
        failures: list[str] = []
        if self.runtime_seconds > budget.target_duration_seconds:
            failures.append("RESOURCE_BUDGET:runtime_seconds")
        if self.peak_memory_bytes is None:
            failures.append("RESOURCE_MEASUREMENT:peak_memory_bytes")
        elif self.peak_memory_bytes > budget.target_memory_bytes:
            failures.append("RESOURCE_BUDGET:peak_memory_bytes")
        if self.temporary_storage_growth_bytes > _TEMPORARY_STORAGE_LIMIT_BYTES:
            failures.append("RESOURCE_BUDGET:temporary_storage_growth_bytes")
        if self.final_managed_storage_bytes > budget.managed_storage_cap_bytes:
            failures.append("RESOURCE_BUDGET:final_managed_storage_bytes")
        if self.free_space_floor_bytes < budget.minimum_free_space_bytes:
            failures.append("RESOURCE_BUDGET:free_space_floor_bytes")
        if self.cpu_heavy_concurrency > budget.maximum_cpu_heavy_operations:
            failures.append("RESOURCE_BUDGET:cpu_heavy_concurrency")
        if self.network_bytes > budget.routine_network_bytes:
            failures.append("RESOURCE_BUDGET:network_bytes")
        return tuple(failures)

    def to_dict(self) -> dict[str, object]:
        return {
            "cpu_heavy_concurrency": self.cpu_heavy_concurrency,
            "final_managed_storage_bytes": self.final_managed_storage_bytes,
            "free_space_floor_bytes": self.free_space_floor_bytes,
            "network_bytes": self.network_bytes,
            "peak_memory_bytes": self.peak_memory_bytes,
            "runtime_seconds": self.runtime_seconds,
            "temporary_storage_growth_bytes": self.temporary_storage_growth_bytes,
        }


@dataclass(frozen=True)
class RecordedReplayResult:
    corpus_digest: str
    league_keys: tuple[str, ...]
    target_match_count: int
    preference_result_count: int
    grade_count: int
    research_only: bool
    production_language: tuple[str, ...]
    replay_digest: str
    report_digest: str
    audit_digest: str
    export_digest: str
    backup_digest: str
    restored_audit_digest: str
    evaluation_digest: str
    evaluation_lifecycle: str
    evaluation_status: str
    details: MappingProxyType[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        for name in (
            "corpus_digest",
            "replay_digest",
            "report_digest",
            "audit_digest",
            "export_digest",
            "backup_digest",
            "restored_audit_digest",
            "evaluation_digest",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))

    def failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        expected_leagues = tuple(league.key for league in TARGET_LEAGUES)
        if self.league_keys != expected_leagues:
            failures.append("REPLAY_LEAGUE_COVERAGE")
        if self.target_match_count != len(expected_leagues):
            failures.append("REPLAY_TARGET_MATCH_COVERAGE")
        if self.preference_result_count != self.target_match_count * 37:
            failures.append("REPLAY_PREFERENCE_COVERAGE")
        if self.grade_count != self.target_match_count * 37:
            failures.append("REPLAY_GRADE_COVERAGE")
        if not self.research_only:
            failures.append("REPLAY_NOT_RESEARCH_ONLY")
        if self.production_language:
            failures.append("REPLAY_PRODUCTION_LANGUAGE")
        if self.audit_digest != self.restored_audit_digest:
            failures.append("RESTORE_NOT_REPRODUCIBLE")
        if self.details.get("grade_identity_digest") != self.details.get(
            "restored_grade_identity_digest"
        ):
            failures.append("RESTORED_GRADES_NOT_REPRODUCIBLE")
        if self.details.get("restored_grade_count") != self.grade_count:
            failures.append("RESTORED_GRADE_COVERAGE")
        if self.evaluation_lifecycle != "EVALUATED_RESEARCH_ONLY":
            failures.append("EVALUATION_NOT_RESEARCH_ONLY")
        if self.evaluation_status != "INCONCLUSIVE":
            failures.append("EVALUATION_UNEXPECTED_STATUS")
        if self.details.get("unspecified_identity_count") != 0:
            failures.append("REPLAY_UNSPECIFIED_IDENTITY")
        if self.details.get("missing_data_inference_count") != 0:
            failures.append("REPLAY_SILENT_MISSING_DATA_INFERENCE")
        if self.details.get("rejected_preference_count") != self.target_match_count * 37:
            failures.append("REPLAY_REJECT_SEMANTICS")
        model_statuses = self.details.get("model_statuses")
        if not isinstance(model_statuses, dict) or any(
            model_statuses.get(status, 0) < 1 for status in ("AVAILABLE", "MODEL_UNAVAILABLE")
        ):
            failures.append("REPLAY_MODEL_AVAILABILITY_SEMANTICS")
        calibration_statuses = self.details.get("calibration_bundle_statuses")
        if (
            not isinstance(calibration_statuses, dict)
            or calibration_statuses.get("MODEL_UNAVAILABLE") != self.target_match_count
        ):
            failures.append("REPLAY_CALIBRATION_UNAVAILABLE_SEMANTICS")
        for key, expected in (
            ("contextual_conflict_count", 1),
            ("fallback_imports", 1),
            ("missing_corner_void_count", 12),
            ("post_cutoff_withdrawal_count", 1),
            ("unknown_weather_count", 2),
            ("withdrawn_fixture_count", 1),
        ):
            if self.details.get(key) != expected:
                failures.append(f"REPLAY_SCENARIO:{key}")
        if self.details.get("prohibited_market_key_count") != 0:
            failures.append("REPLAY_PROHIBITED_MARKET_LEAKAGE")
        evaluated = self.details.get("chronological_evaluated_target_count")
        unavailable = self.details.get("chronological_model_unavailable_exclusion_count")
        if (
            not isinstance(evaluated, int)
            or evaluated < 0
            or not isinstance(unavailable, int)
            or evaluated + unavailable != self.target_match_count
        ):
            failures.append("EVALUATION_TARGET_PROVENANCE_COVERAGE")
        if self.details.get("chronological_framework_observation_count") != 1:
            failures.append("EVALUATION_FRAMEWORK_SMOKE_COVERAGE")
        return tuple(failures)

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_digest": self.audit_digest,
            "backup_digest": self.backup_digest,
            "corpus_digest": self.corpus_digest,
            "details": dict(self.details),
            "evaluation_digest": self.evaluation_digest,
            "evaluation_lifecycle": self.evaluation_lifecycle,
            "evaluation_status": self.evaluation_status,
            "export_digest": self.export_digest,
            "grade_count": self.grade_count,
            "league_keys": self.league_keys,
            "preference_result_count": self.preference_result_count,
            "production_language": self.production_language,
            "replay_digest": self.replay_digest,
            "report_digest": self.report_digest,
            "research_only": self.research_only,
            "restored_audit_digest": self.restored_audit_digest,
            "target_match_count": self.target_match_count,
        }


@dataclass(frozen=True)
class QualificationEvidence:
    software_commit: str
    environment_digest: str
    gates: tuple[GateEvidence, ...]
    replay: RecordedReplayResult
    deterministic_replay_digest: str
    resources: ResourceMeasurement
    known_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "software_commit",
            _git_id(self.software_commit, "Qualified software commit"),
        )
        object.__setattr__(
            self, "environment_digest", _sha256(self.environment_digest, "Environment")
        )
        object.__setattr__(
            self,
            "deterministic_replay_digest",
            _sha256(self.deterministic_replay_digest, "Deterministic replay"),
        )
        if len({gate.name for gate in self.gates}) != len(self.gates):
            raise T19ValidationError("Qualification gate names must be unique.")
        if not self.known_limitations:
            raise T19ValidationError("Qualification must record known limitations.")


@dataclass(frozen=True)
class QualificationManifest:
    status: QualificationStatus
    software_commit: str
    environment_digest: str
    gates: tuple[GateEvidence, ...]
    replay: RecordedReplayResult
    resources: ResourceMeasurement
    known_limitations: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    mode: str = "RESEARCH_ONLY"
    production_promotion: bool = False
    schema: str = T19_QUALIFICATION_SCHEMA
    digest: str = ""

    def __post_init__(self) -> None:
        if self.mode != "RESEARCH_ONLY" or self.production_promotion:
            raise T19ValidationError("T19 can record only a research-only software release.")
        expected = _digest(self._payload())
        if self.digest and self.digest != expected:
            raise T19ValidationError("Qualification manifest digest does not match its content.")
        object.__setattr__(self, "digest", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "environment_digest": self.environment_digest,
            "failure_reasons": self.failure_reasons,
            "gates": [gate.to_dict() for gate in self.gates],
            "known_limitations": self.known_limitations,
            "mode": self.mode,
            "production_promotion": self.production_promotion,
            "replay": self.replay.to_dict(),
            "resources": self.resources.to_dict(),
            "schema": self.schema,
            "software_commit": self.software_commit,
            "status": self.status.value,
        }

    def to_bytes(self) -> bytes:
        return _canonical_json({**self._payload(), "digest": self.digest})


def qualify_research_only(evidence: QualificationEvidence) -> QualificationManifest:
    """Evaluate the fixed T19 software gates without promoting a policy."""

    gates_by_name = {gate.name: gate for gate in evidence.gates}
    failures: list[str] = []
    for name in REQUIRED_QUALIFICATION_GATES:
        gate = gates_by_name.get(name)
        if gate is None:
            failures.append(f"MISSING_GATE:{name}")
        elif gate.status is not GateStatus.PASS or gate.exit_code != 0:
            failures.append(f"FAILED_GATE:{name}")
    unexpected = sorted(set(gates_by_name) - set(REQUIRED_QUALIFICATION_GATES))
    failures.extend(f"UNEXPECTED_GATE:{name}" for name in unexpected)
    failures.extend(evidence.replay.failures())
    if evidence.replay.replay_digest != evidence.deterministic_replay_digest:
        failures.append("REPLAY_NOT_DETERMINISTIC")
    failures.extend(evidence.resources.failures())
    status = (
        QualificationStatus.NOT_QUALIFIED
        if failures
        else QualificationStatus.QUALIFIED_RESEARCH_ONLY
    )
    return QualificationManifest(
        status=status,
        software_commit=evidence.software_commit,
        environment_digest=evidence.environment_digest,
        gates=tuple(sorted(evidence.gates, key=lambda gate: gate.name)),
        replay=evidence.replay,
        resources=evidence.resources,
        known_limitations=evidence.known_limitations,
        failure_reasons=tuple(failures),
    )


def _football_data_bytes(pack: RecordedLeaguePack, division: str) -> bytes:
    header = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC"
    pairs = (("A", "C"), ("D", "B"), ("C", "A"), ("B", "D"), ("A", "D"), ("C", "B"))
    dates = ("01/07/2026", "08/07/2026", "15/07/2026", "22/07/2026", "01/08/2026", "15/08/2026")
    rows = [header]
    for date_text, pair, result in zip(dates, pairs, pack.history_results, strict=True):
        home, away, half_home, half_away, corners_home, corners_away = result
        full_time_result = (
            ""
            if home is None or away is None
            else ("H" if home > away else "A" if home < away else "D")
        )
        values: tuple[object, ...] = (
            division,
            date_text,
            "20:00",
            f"{pack.team_prefix} {pair[0]}",
            f"{pack.team_prefix} {pair[1]}",
            home,
            away,
            full_time_result,
            half_home,
            half_away,
            corners_home,
            corners_away,
        )
        rows.append(",".join("" if value is None else str(value) for value in values))
    rows.append(
        ",".join(
            (
                division,
                pack.target_date,
                pack.target_time,
                f"{pack.team_prefix} A",
                f"{pack.team_prefix} B",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            )
        )
    )
    return ("\n".join(rows) + "\n").encode()


def _openfootball_bytes(pack: RecordedLeaguePack) -> bytes:
    pairs = (("A", "C"), ("D", "B"), ("C", "A"), ("B", "D"), ("A", "D"), ("C", "B"))
    dates = ("2026-07-01", "2026-07-08", "2026-07-15", "2026-07-22", "2026-08-01", "2026-08-15")
    matches: list[dict[str, object]] = []
    for index, (date_text, pair, result) in enumerate(
        zip(dates, pairs, pack.history_results, strict=True), start=1
    ):
        home, away, half_home, half_away, _corners_home, _corners_away = result
        matches.append(
            {
                "date": date_text,
                "round": f"Matchday {index}",
                "score": {"ft": [home, away], "ht": [half_home, half_away]},
                "team1": f"{pack.team_prefix} {pair[0]}",
                "team2": f"{pack.team_prefix} {pair[1]}",
                "time": "20:00",
            }
        )
    target_date = datetime.strptime(pack.target_date, "%d/%m/%Y").date().isoformat()
    matches.append(
        {
            "date": target_date,
            "round": "Matchday 7",
            "score": {},
            "team1": f"{pack.team_prefix} A",
            "team2": f"{pack.team_prefix} B",
            "time": pack.target_time,
        }
    )
    return _canonical_json({"matches": matches, "name": "MatchVet recorded qualification"})


def run_recorded_replay(
    corpus: RecordedCorpus,
    workspace: Path,
    *,
    software_commit: str = "0" * 40,
) -> RecordedReplayResult:
    """Run the rights-safe seven-league corpus through the implemented pipeline."""

    software_commit = _git_id(software_commit, "Replay software commit")

    from matchvet.evidence import (
        EvidenceAssertionInput,
        EvidenceAssertionRecord,
        EvidenceRecorder,
        EvidenceType,
        IndependentOrigin,
        SourceIdentity,
        SubjectKind,
    )
    from matchvet.evidence import (
        SourceCaptureInput as ContextCaptureInput,
    )
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        FootballDataCSVParser,
        IngestionPlan,
        SourceCaptureInput,
        StaticSourceFetcher,
        T06AcquisitionRunner,
        football_data_url,
        league_by_key,
        openfootball_url,
    )
    from matchvet.matchweek import (
        AppendixDisposition,
        append_post_cutoff_revision,
        freeze_matchweek,
        read_frozen_matchweek,
    )
    from matchvet.store import open_store
    from matchvet.t08 import T08EvidenceRunner, T08Plan
    from matchvet.t09 import T09EvidenceRunner, T09Plan
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    workspace.mkdir(parents=True, exist_ok=False)
    logical_verification_time = datetime.fromisoformat(corpus.captured_at_utc).isoformat(
        timespec="microseconds"
    )
    private_root = workspace / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    sources: dict[str, bytes] = {}
    for pack, league in zip(corpus.leagues, TARGET_LEAGUES, strict=True):
        if pack.source_mode == "OPENFOOTBALL_FALLBACK":
            sources[openfootball_url(league, corpus.season)] = _openfootball_bytes(pack)
        else:
            sources[football_data_url(league, corpus.season)] = _football_data_bytes(
                pack, league.football_data_code
            )
    store = open_store(database_path, private_root=private_root)
    try:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        acquirer = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(sources, retrieved_at_utc=corpus.captured_at_utc),
        )
        ingestion = T06AcquisitionRunner(store, acquirer)
        ingestion.start(
            IngestionPlan(current_season=corpus.season),
            observation=observe_resources(database_path),
        )
        report = ingestion.last_report
        if report is None or len(report.imports) != len(TARGET_LEAGUES):
            raise T19Error("Recorded T06 acquisition did not import all seven league packs.")
        freeze = freeze_matchweek(
            store,
            corpus.matchweek_friday,
            season=corpus.season,
            as_of_utc=corpus.captured_at_utc,
            created_at_utc=corpus.captured_at_utc,
            manifest_verified_at_utc=logical_verification_time,
        )
        if len(freeze.target_matches) != len(TARGET_LEAGUES):
            raise T19Error("Recorded T05 freeze did not retain all seven target matches.")
        withdrawn_league = corpus.scenarios["withdrawn_league"]
        withdrawn_pack = next(
            pack for pack in corpus.leagues if pack.league_key == withdrawn_league
        )
        withdrawn_definition = league_by_key(withdrawn_league)
        original_content = _football_data_bytes(
            withdrawn_pack, withdrawn_definition.football_data_code
        )
        revised_content = original_content.replace(
            withdrawn_pack.target_date.encode("ascii"), b"25/09/2026", 1
        )
        importer.import_dataset(
            FootballDataCSVParser().parse(
                revised_content,
                league=withdrawn_definition,
                season=corpus.season,
            ),
            revised_content,
            SourceCaptureInput(
                source_url=football_data_url(withdrawn_definition, corpus.season),
                retrieved_at_utc="2026-09-18T14:00:00+00:00",
                observed_terms="private self-authored structural qualification capture",
            ),
        )
        withdrawn_fixture = next(
            item for item in importer.fixtures() if item.league_key == withdrawn_league
        )
        withdrawn_target = next(
            item
            for item in freeze.target_matches
            if item.subject_id == withdrawn_fixture.fixture_id
        )
        withdrawal = append_post_cutoff_revision(
            store,
            corpus.matchweek_friday,
            withdrawn_target.subject_id,
            season=corpus.season,
            as_of_utc="2026-09-18T14:00:00+00:00",
        )
        if withdrawal.disposition is not AppendixDisposition.WITHDRAWN:
            raise T19Error("Recorded post-cutoff move did not withdraw the frozen target.")
        freeze = read_frozen_matchweek(store, corpus.matchweek_friday, season=corpus.season)

        contextual_assertions: list[EvidenceAssertionRecord] = []
        contextual_conflict_count = 0
        conflict_target = freeze.target_matches[0].subject_id
        evidence_recorder = EvidenceRecorder(store)
        for suffix, shape in (("a", "compact"), ("b", "wide")):
            recorded = evidence_recorder.ingest(
                ContextCaptureInput(
                    source=SourceIdentity(
                        source_key=f"t19-official-context-{suffix}",
                        canonical_name=f"T19 Official Context {suffix.upper()}",
                        owner="MatchVet qualification corpus",
                        source_class="OFFICIAL_CLUB",
                        access_method="MANUAL_CITATION",
                        base_locator=f"https://example.invalid/t19/{suffix}/",
                        allowed_use="CITATION_ONLY",
                        retention_status="CITATION_ONLY",
                        redistributable=False,
                        terms_reference="Self-authored structural qualification fixture",
                    ),
                    origin=IndependentOrigin(
                        origin_key=f"t19-context-origin-{suffix}",
                        organization=f"T19 Context Origin {suffix.upper()}",
                        classification="DIRECT_ORIGIN",
                    ),
                    locator=f"https://example.invalid/t19/{suffix}/tactics",
                    retrieved_at_utc=corpus.captured_at_utc,
                    published_at_utc=corpus.captured_at_utc,
                    capture_key=f"t19-context-{suffix}",
                    citation_note="Self-authored contradictory context for conflict handling.",
                ),
                (
                    EvidenceAssertionInput(
                        SubjectKind.FIXTURE,
                        conflict_target,
                        EvidenceType.TACTICAL_CONTEXT,
                        "shape",
                        value=shape,
                        assertion_key=f"shape-{suffix}",
                    ),
                ),
                cutoff_utc=freeze.cutoff.cutoff_utc,
            )
            contextual_assertions.extend(recorded.assertions)
            contextual_conflict_count += len(recorded.conflicts)

        locations: dict[str, VenueLocation] = {}
        responses: dict[str, dict[str, object]] = {}
        unknown_weather_index = corpus.league_keys.index(corpus.scenarios["unknown_context_league"])
        for index, membership in enumerate(freeze.target_matches):
            if index == unknown_weather_index:
                continue
            location = VenueLocation(
                venue_id=membership.subject_id,
                venue_name="Recorded Qualification Stadium",
                latitude=6.5244,
                longitude=3.3792,
                source_key="self-authored-corpus",
                locator=f"corpus:{corpus.digest}",
                observed_at_utc=corpus.captured_at_utc,
            )
            locations[membership.subject_id] = location
            request = WeatherRequest(
                membership.subject_id,
                membership.original_kickoff_utc or "",
                freeze.cutoff.cutoff_utc,
                location,
            )
            issue = datetime.fromisoformat(freeze.cutoff.cutoff_utc) - timedelta(hours=1)
            responses[request.url] = {
                "forecast_issue_time": issue.isoformat().replace("+00:00", "Z"),
                "hourly": {"temperature_2m": [27.0], "time": [request.interval_start_utc]},
                "hourly_units": {"temperature_2m": "°C"},
                "latitude": location.latitude,
                "longitude": location.longitude,
                "model": "best_match",
            }
        weather_client = StaticWeatherClient(
            responses,
            retrieved_at_utc=freeze.cutoff.cutoff_utc,
        )
        t08_runner = T08EvidenceRunner(store)
        t08_runner.start(
            T08Plan(corpus.matchweek_friday, corpus.season),
            observation=observe_resources(database_path),
            weather_client=weather_client,
            locations=locations,
        )
        if t08_runner.last_result is None:
            raise T19Error("Recorded T08 evidence run did not produce a result.")
        t09_runner = T09EvidenceRunner(store)
        t09_runner.start(
            T09Plan(corpus.matchweek_friday, corpus.season),
            observation=observe_resources(database_path),
            t08_evidence=t08_runner.last_result.evidence,
            contextual_assertions=tuple(contextual_assertions),
            manifest_verified_at_utc=logical_verification_time,
        )
        if t09_runner.last_result is None:
            raise T19Error("Recorded T09 evidence run did not produce a result.")
        return _complete_recorded_replay(
            corpus,
            workspace,
            database_path,
            private_root,
            store,
            freeze,
            report,
            t08_runner.last_result.evidence,
            t09_runner.last_result.states,
            contextual_conflict_count,
            software_commit,
        )
    finally:
        store.close()


def _tree_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, _directories, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _observed_memory_bytes() -> int | None:
    try:
        fields = (Path("/proc/self/status")).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values: dict[str, int] = {}
    for line in fields:
        if line.startswith(("VmHWM:", "VmRSS:")):
            name, raw = line.split(":", 1)
            parts = raw.split()
            if parts and parts[0].isdigit():
                values[name] = int(parts[0]) * 1024
    return values.get("VmHWM", values.get("VmRSS"))


def _observed_thread_count() -> int | None:
    try:
        return len(tuple(Path("/proc/self/task").iterdir()))
    except OSError:
        return None


@contextmanager
def _offline_network_guard() -> Iterator[None]:
    active = True

    def reject_network(event: str, _arguments: tuple[object, ...]) -> None:
        if active and event in {"socket.connect", "socket.sendto"}:
            raise T19Error(f"Recorded replay attempted a network operation: {event}.")

    sys.addaudithook(reject_network)
    try:
        yield
    finally:
        active = False


def measure_recorded_replay(
    corpus: RecordedCorpus,
    workspace: Path,
    *,
    software_commit: str = "0" * 40,
) -> tuple[RecordedReplayResult, ResourceMeasurement]:
    """Measure one offline replay on the current device using OS observations."""

    parent = workspace.parent
    parent.mkdir(parents=True, exist_ok=True)
    initial_size = _tree_size(workspace)
    initial_free = os.statvfs(parent).f_bavail * os.statvfs(parent).f_frsize
    peak_size = initial_size
    free_floor = initial_free
    peak_memory = _observed_memory_bytes()
    peak_threads = _observed_thread_count()
    stopped = threading.Event()

    def observe() -> None:
        nonlocal peak_size, free_floor, peak_memory, peak_threads
        while not stopped.wait(0.25):
            peak_size = max(peak_size, _tree_size(workspace))
            stats = os.statvfs(parent)
            free_floor = min(free_floor, stats.f_bavail * stats.f_frsize)
            memory = _observed_memory_bytes()
            if memory is not None:
                peak_memory = memory if peak_memory is None else max(peak_memory, memory)
            thread_count = _observed_thread_count()
            if thread_count is not None:
                peak_threads = (
                    thread_count if peak_threads is None else max(peak_threads, thread_count)
                )

    observer = threading.Thread(target=observe, name="t19-resource-observer", daemon=True)
    observer.start()
    started = time.monotonic()
    try:
        with _offline_network_guard():
            result = run_recorded_replay(corpus, workspace, software_commit=software_commit)
    finally:
        stopped.set()
        observer.join()
    runtime_seconds = time.monotonic() - started
    final_size = _tree_size(workspace)
    stats = os.statvfs(parent)
    free_floor = min(free_floor, stats.f_bavail * stats.f_frsize)
    memory = _observed_memory_bytes()
    if memory is not None:
        peak_memory = memory if peak_memory is None else max(peak_memory, memory)
    thread_count = _observed_thread_count()
    if thread_count is not None:
        peak_threads = thread_count if peak_threads is None else max(peak_threads, thread_count)
    if peak_threads is None:
        raise T19Error("Device thread count could not be observed during the replay.")
    measurement = ResourceMeasurement(
        runtime_seconds=runtime_seconds,
        peak_memory_bytes=peak_memory,
        temporary_storage_growth_bytes=max(0, peak_size - final_size),
        final_managed_storage_bytes=final_size,
        free_space_floor_bytes=free_floor,
        cpu_heavy_concurrency=peak_threads,
        network_bytes=0,
    )
    return result, measurement


def _chronological_evaluation(
    workspace: Path,
    policy_digest: str,
    target_sources: tuple[MappingProxyType[str, object], ...],
) -> tuple[str, str, str]:
    from matchvet.t18 import (
        CandidatePolicy,
        ChronologicalPeriod,
        EvaluationConfig,
        EvaluationRunner,
        HistoricalEvaluation,
    )

    candidate = CandidatePolicy(
        version="t19-research-v1",
        digest=policy_digest,
        development_data_end_utc="2026-07-15T00:00:00+00:00",
        frozen_at_utc="2026-09-17T00:00:00+00:00",
        parameters={"qualification": "framework-only"},
    )

    def observation(
        label: str,
        start: str,
        kickoff: str,
        cutoff: str,
        known: str,
        settlement: str,
    ) -> HistoricalEvaluation:
        source = {
            "capture_class": "SELF_AUTHORED_STRUCTURAL_EQUIVALENT",
            "fixture_id": f"t19-chronology-{label}",
            "known_at_utc": known,
            "settlement": settlement,
        }
        revision = {
            "kickoff_at_utc": kickoff,
            "match_id": f"t19-{label}",
            "source_fixture_id": source["fixture_id"],
            "source_grade_digest": _digest(source),
        }
        revision_digest = _digest(revision)
        manifest = {
            "fixture_revision_digests": [revision_digest],
            "matchweek_id": f"mw-{label}",
            "source_membership_manifest_digest": _digest(
                {"fixture_id": source["fixture_id"], "cutoff": cutoff}
            ),
        }
        return HistoricalEvaluation(
            match_id=f"t19-{label}",
            matchweek_id=f"mw-{label}",
            matchweek_start_utc=start,
            kickoff_at_utc=kickoff,
            research_cutoff_at_utc=cutoff,
            prediction_created_at_utc=cutoff,
            outcome_known_at_utc=known,
            league="Recorded Qualification League",
            preference_id="match_winner_home",
            preference_family="Match Winner",
            exact_line="Home",
            policy_version=candidate.version,
            policy_digest=candidate.digest,
            model_version="t19-structural-model-v1",
            model_digest=_digest({"kind": "t19-chronology-model", "frozen": start}),
            evidence_digest=_digest({"source": source, "cutoff": cutoff}),
            input_digest=_digest(source),
            estimated_probability=0.6,
            conservative_probability=0.5,
            uncertainty_lower=0.4,
            uncertainty_upper=0.7,
            settlement=settlement,
            recommendation="REJECT",
            correlation_group="match-result",
            input_observed_at_utc={
                "fixture_revision": start,
                "membership_manifest": start,
            },
            membership_manifest=manifest,
            membership_manifest_digest=_digest(manifest),
            fixture_revision=revision,
            fixture_revision_digest=revision_digest,
            training_data_end_utc=start,
            model_fitted_at_utc=start,
            calibration_digest=_digest({"kind": "t19-chronology-calibration", "frozen": start}),
            baseline_digest=_digest(
                {
                    "kind": "t19-framework-baseline",
                    "source_evidence_digest": _digest({"source": source, "cutoff": cutoff}),
                }
            ),
        )

    development_observations = (
        observation(
            "development",
            "2026-06-30T00:00:00+00:00",
            "2026-07-01T14:00:00+00:00",
            "2026-07-01T08:00:00+00:00",
            "2026-07-01T18:00:00+00:00",
            "WIN",
        ),
        observation(
            "validation",
            "2026-08-01T00:00:00+00:00",
            "2026-08-15T14:00:00+00:00",
            "2026-08-15T08:00:00+00:00",
            "2026-08-15T18:00:00+00:00",
            "LOSS",
        ),
        observation(
            "evaluation-framework",
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T10:00:00+00:00",
            "2026-09-18T04:00:00+00:00",
            "2026-09-18T14:00:00+00:00",
            "WIN",
        ),
    )
    target_observations: list[HistoricalEvaluation] = []
    for source in target_sources:
        kickoff_at_utc = _utc_text(source["kickoff_at_utc"], "Evaluation kickoff")
        revision = {
            "kickoff_at_utc": kickoff_at_utc,
            "match_id": source["fixture_id"],
            "source_revision_digest": source["source_revision_digest"],
        }
        revision_digest = _digest(revision)
        manifest = {
            "fixture_revision_digests": [revision_digest],
            "matchweek_id": source["matchweek_id"],
            "source_membership_manifest_digest": source["membership_manifest_digest"],
        }
        target_observations.append(
            HistoricalEvaluation(
                match_id=str(source["fixture_id"]),
                matchweek_id=str(source["matchweek_id"]),
                matchweek_start_utc=str(source["matchweek_start_utc"]),
                kickoff_at_utc=kickoff_at_utc,
                research_cutoff_at_utc=str(source["cutoff_utc"]),
                prediction_created_at_utc=str(source["cutoff_utc"]),
                outcome_known_at_utc=str(source["outcome_known_at_utc"]),
                league=str(source["league"]),
                preference_id=str(source["preference_id"]),
                preference_family=str(source["preference_family"]),
                exact_line=str(source["exact_line"]),
                policy_version=candidate.version,
                policy_digest=candidate.digest,
                model_version=str(source["model_version"]),
                model_digest=str(source["model_digest"]),
                evidence_digest=str(source["evidence_digest"]),
                input_digest=_digest(dict(source)),
                estimated_probability=cast(float, source["estimated_probability"]),
                conservative_probability=cast(float, source["conservative_probability"]),
                uncertainty_lower=cast(float, source["uncertainty_lower"]),
                uncertainty_upper=cast(float, source["uncertainty_upper"]),
                settlement=str(source["settlement"]),
                recommendation="REJECT",
                correlation_group=str(source["correlation_group"]),
                input_observed_at_utc={
                    "fixture_revision": str(source["fixture_observed_at_utc"]),
                    "membership_manifest": str(source["cutoff_utc"]),
                },
                membership_manifest=manifest,
                membership_manifest_digest=_digest(manifest),
                fixture_revision=revision,
                fixture_revision_digest=revision_digest,
                training_data_end_utc="2026-08-15T18:00:00+00:00",
                model_fitted_at_utc=str(source["cutoff_utc"]),
                calibration_digest=str(source["calibration_digest"]),
                baseline_digest=_digest(
                    {
                        "kind": "t19-recorded-target-baseline",
                        "fixture_id": source["fixture_id"],
                    }
                ),
                settlement_distribution=cast(
                    Mapping[str, float], source["settlement_distribution"]
                ),
            )
        )
    observations = (*development_observations, *target_observations)
    config = EvaluationConfig(
        development=ChronologicalPeriod(
            "DEVELOPMENT", "2026-06-30T00:00:00+00:00", "2026-07-15T00:00:00+00:00"
        ),
        validation=ChronologicalPeriod(
            "VALIDATION", "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"
        ),
        evaluation=ChronologicalPeriod(
            "EVALUATION", "2026-09-17T00:00:00+00:00", "2026-10-01T00:00:00+00:00"
        ),
        minimum_development_matchweeks=1,
        rolling_validation_matchweeks=1,
        rolling_step_matchweeks=1,
        seed=19,
    )
    artifact = EvaluationRunner(workspace / "evaluation-checkpoint.json").run(
        observations, (candidate,), config
    )
    return artifact.digest, artifact.lifecycle_effect, artifact.status


def _complete_recorded_replay(
    corpus: RecordedCorpus,
    workspace: Path,
    database_path: Path,
    private_root: Path,
    store: Store,
    freeze: MatchweekFreeze,
    ingestion_report: AcquisitionReport,
    t08_evidence: T08Evidence,
    states: tuple[FrozenEvidenceState, ...],
    contextual_conflict_count: int,
    software_commit: str,
) -> RecordedReplayResult:
    from matchvet.t10 import (
        SettlementEvidence,
        SettlementGrade,
        SettlementGradeRecorder,
        grade_all_preferences,
    )
    from matchvet.t11 import T11ArtifactRecorder, fit_full_time_goal_model_from_store
    from matchvet.t12 import HalfPhase, T12ArtifactRecorder, fit_half_goal_model_from_store
    from matchvet.t13 import T13ArtifactRecorder, fit_joint_corner_model_from_store
    from matchvet.t14 import CalibrationBundle, calibrate_model_families
    from matchvet.t15 import PolicyVersion, vet_matchweek
    from matchvet.t16 import (
        build_matchweek_audit,
        publish_matchweek_audit,
        read_audit,
        render_markdown_report,
    )
    from matchvet.t17 import backup_store, export_matchweek, restore_backup

    model_statuses = {"AVAILABLE": 0, "MODEL_UNAVAILABLE": 0}
    calibration_bundle_statuses = {"AVAILABLE": 0, "MODEL_UNAVAILABLE": 0, "REJECT": 0}
    predictions: dict[str, object] = {}
    state_by_fixture: dict[str, object] = {}
    fit_digests: list[str] = []
    packs_by_league = {pack.league_key: pack for pack in corpus.leagues}
    full_recorder = T11ArtifactRecorder(store)
    half_recorder = T12ArtifactRecorder(store)
    corner_recorder = T13ArtifactRecorder(store)
    for state in states:
        fixture_id = str(state.target_fixture_id)
        state_by_fixture[fixture_id] = state
        full_fit = fit_full_time_goal_model_from_store(store, state)
        first_fit = fit_half_goal_model_from_store(store, state, HalfPhase.FIRST_HALF)
        second_fit = fit_half_goal_model_from_store(store, state, HalfPhase.SECOND_HALF)
        corner_fit = fit_joint_corner_model_from_store(store, state)
        full = full_recorder.publish(full_fit, full_fit.predict(state))
        first = half_recorder.publish(first_fit, first_fit.predict(state))
        second = half_recorder.publish(second_fit, second_fit.predict(state))
        corners = corner_recorder.publish(corner_fit, corner_fit.predict(state))
        full_fit = full.fit
        first_fit = first.fit
        second_fit = second.fit
        corner_fit = corners.fit
        fits = (full_fit, first_fit, second_fit, corner_fit)
        for fit in fits:
            model_statuses[fit.status.value] += 1
            fit_digests.append(fit.digest)
        bundle = calibrate_model_families(
            full_time=full.distribution,
            first_half=first.distribution,
            second_half=second.distribution,
            corners=corners.distribution,
            calibration_records=(),
            frozen_evidence_state=state,
            model_fits={
                "full_time": full_fit,
                "first_half": first_fit,
                "second_half": second_fit,
                "corners": corner_fit,
            },
            seed=19,
        )
        calibration_bundle_statuses[bundle.status.value] += 1
        predictions[fixture_id] = bundle

    policy = PolicyVersion(version="t19-research-v1")
    vetting = vet_matchweek(state_by_fixture, predictions, policy)
    results_by_fixture = {
        str(cast("TargetMatch", item.target).fixture_id): item for item in vetting.matches
    }
    preference_result_count = sum(len(item.preference_results) for item in vetting.matches)
    production_findings = {
        item.decision.value
        for item in vetting.matches
        if item.decision.value in {"PLAY", "AVOID_MATCH"}
    }
    production_findings.update(
        "PRODUCTION_PREFERENCE_OUTPUT"
        for item in vetting.matches
        for row in item.preference_results
        if row.is_production_output
    )
    if policy.production_promoted:
        production_findings.add("PRODUCTION_PROMOTED_POLICY")

    recorded_grades: list[SettlementGrade] = []
    grade_recorder = SettlementGradeRecorder(store)
    withdrawn_league = corpus.scenarios["withdrawn_league"]
    missing_corners_league = corpus.scenarios["missing_corners_league"]
    withdrawn_ids: list[str] = []
    missing_corner_void_count = 0
    missing_data_inference_count = 0
    for state in states:
        target = state.target
        pack = packs_by_league[target.competition_key]
        settlement = SettlementEvidence(
            fixture_id=target.fixture_id,
            source_key="self-authored-qualification-corpus",
            record_id=f"settlement:{target.fixture_id}",
            source_digest=corpus.digest,
            fixture_status="COMPLETED",
            regulation_completed=True,
            full_time_home_goals=pack.settlement[0],
            full_time_away_goals=pack.settlement[1],
            half_time_home_goals=pack.settlement[2],
            half_time_away_goals=pack.settlement[3],
            corners_home=pack.settlement[4],
            corners_away=pack.settlement[5],
            observed_at_utc="2026-09-22T12:00:00+00:00",
            provenance={"corpus_digest": corpus.digest, "rights": corpus.rights.to_dict()},
        )
        withdrawn = target.competition_key == withdrawn_league
        if withdrawn:
            withdrawn_ids.append(target.fixture_id)
        grades = grade_all_preferences(
            (settlement,),
            fixture_id=target.fixture_id,
            finalize=True,
            withdrawn=withdrawn,
            matchweek_id=freeze.cutoff.matchweek_id,
            frozen_evidence_digest=state.digest,
        )
        if target.competition_key == missing_corners_league:
            corner_grades = tuple(
                grade for grade in grades if "Corner" in grade.preference.family.value
            )
            missing_corner_void_count += sum(
                grade.settlement_result is not None and grade.settlement_result.value == "VOID"
                for grade in corner_grades
            )
            missing_data_inference_count += sum(
                grade.settlement_result is None or grade.settlement_result.value != "VOID"
                for grade in corner_grades
            )
        recorded_grades.extend(grade_recorder.record_many(grades))
    grade_count = len(recorded_grades)
    grade_identity_digest = _digest(sorted(grade.grade_digest for grade in recorded_grades))

    reproducibility = {
        "matchweek_id": freeze.cutoff.matchweek_id,
        "window_start_local": freeze.window.start_local.isoformat(),
        "window_end_local": freeze.window.end_local.isoformat(),
        "target_league_set_version": "2026-27-target-leagues-v1",
        "model_version": "t11-t13-v1",
        "feature_version": "t09-feature-rules-v1",
        "research_rules_version": "t09-research-rules-v1",
        "data_snapshot_digest": freeze.snapshot_manifest_digest,
        "data_snapshot_id": freeze.snapshot_manifest_digest,
        "environment_digest": _digest({"runtime": "termux", "source": "recorded-offline"}),
        "matchweek_membership_manifest_digest": freeze.membership_manifest_digest,
        "matchweek_research_cutoff_utc": freeze.cutoff.cutoff_utc,
        "matchweek_snapshot_digest": freeze.snapshot_manifest_digest,
        "retrieval_cutoff": freeze.cutoff.cutoff_utc,
        "retrieval_cutoff_id": freeze.cutoff.cutoff_id,
        "revision_snapshot_digest": freeze.revision_snapshot_digest,
        "software_commit": software_commit,
        "corpus_digest": corpus.digest,
    }
    audit = build_matchweek_audit(
        freeze.cutoff.matchweek_id,
        freeze.memberships,
        results_by_fixture,
        evidence_states=state_by_fixture,
        predictions=predictions,
        policy=policy,
        appendix=freeze.appendix,
        withdrawn_fixture_ids=withdrawn_ids,
        reproducibility=reproducibility,
    )
    publication = publish_matchweek_audit(audit, store=store)
    report_text = render_markdown_report(audit)
    audit_bytes = audit.to_bytes()
    audit_payload = json.loads(audit_bytes)
    prohibited_market_keys = _prohibited_market_keys(audit_payload)
    if audit.mode.value != "RESEARCH_ONLY":
        production_findings.add(f"AUDIT_MODE:{audit.mode.value}")
    audit_text = audit_bytes.decode("utf-8")
    for marker in ('"decision":"PLAY"', '"status":"PRIMARY_RECOMMENDATION"'):
        if marker in audit_text:
            production_findings.add(marker)
    for marker in ("**Decision:** PLAY", "**Mode:** PRODUCTION"):
        if marker in report_text:
            production_findings.add(marker)
    production_language = tuple(sorted(production_findings))
    shared_root = workspace / "shared"
    shared_root.mkdir()
    export = export_matchweek(
        database_path,
        shared_root / "export",
        private_root=private_root,
        matchweek_id=freeze.cutoff.matchweek_id,
        resource_observation=observe_resources(database_path),
    )
    backup = backup_store(
        database_path,
        shared_root / "backup",
        private_root=private_root,
        resource_observation=observe_resources(database_path),
    )
    restored_root = workspace / "restored-private"
    restored_root.mkdir()
    restored_database = restored_root / "matchvet.sqlite3"
    restore_backup(
        shared_root / "backup",
        restored_database,
        private_root=restored_root,
        resource_observation=observe_resources(database_path),
    )
    restored_audit = read_audit(
        restored_database,
        private_root=restored_root,
        matchweek_id=freeze.cutoff.matchweek_id,
    )
    from matchvet.store import open_store

    restored_store = open_store(restored_database, private_root=restored_root)
    try:
        restored_grades = SettlementGradeRecorder(restored_store).grades()
    finally:
        restored_store.close()
    restored_grade_identity_digest = _digest(
        sorted(grade.grade_digest for grade in restored_grades)
    )
    evaluation_sources: list[MappingProxyType[str, object]] = []
    chronological_model_unavailable_exclusion_count = 0
    for state in sorted(states, key=lambda item: item.target_fixture_id):
        fixture_id = str(state.target_fixture_id)
        membership = next(item for item in freeze.memberships if item.subject_id == fixture_id)
        if membership.controlling_revision_digest is None:
            raise T19Error("Recorded target lacks its controlling Fixture Revision digest.")
        bundle = cast(CalibrationBundle, predictions[fixture_id])
        selected = next(
            (
                (distribution, preference_id)
                for _family, distribution in sorted(bundle.predictions.items())
                for preference_id in sorted(distribution.estimated_probabilities)
            ),
            None,
        )
        if selected is None:
            chronological_model_unavailable_exclusion_count += 1
            continue
        distribution, preference_id = selected
        grade = next(
            item
            for item in recorded_grades
            if item.fixture_id == fixture_id and item.preference.preference_id == preference_id
        )
        if grade.settlement_result is None:
            raise T19Error("Recorded target lacks a final grade for its evaluation preference.")
        interval = distribution.probability_intervals[preference_id]["WIN"]
        settlement_distribution = distribution.settlement_distributions[preference_id]
        evaluation_sources.append(
            MappingProxyType(
                {
                    "calibration_digest": distribution.calibration_digest or bundle.digest,
                    "conservative_probability": distribution.conservative_probabilities[
                        preference_id
                    ],
                    "correlation_group": grade.preference.family.value,
                    "cutoff_utc": freeze.cutoff.cutoff_utc,
                    "estimated_probability": distribution.estimated_probabilities[preference_id],
                    "evidence_digest": state.digest,
                    "fixture_id": fixture_id,
                    "fixture_observed_at_utc": corpus.captured_at_utc,
                    "kickoff_at_utc": state.target.kickoff_utc,
                    "league": state.target.competition_name,
                    "matchweek_id": freeze.cutoff.matchweek_id,
                    "matchweek_start_utc": freeze.window.start_utc,
                    "membership_manifest_digest": freeze.membership_manifest_digest,
                    "model_digest": distribution.model_digest,
                    "model_version": distribution.model_version,
                    "outcome_known_at_utc": "2026-09-22T12:00:00+00:00",
                    "exact_line": grade.preference.label,
                    "preference_family": grade.preference.family.value,
                    "preference_id": preference_id,
                    "settlement": grade.settlement_result.value,
                    "settlement_distribution": {
                        "LOSS": settlement_distribution.loss,
                        "PUSH": settlement_distribution.push,
                        "WIN": settlement_distribution.win,
                    },
                    "source_revision_digest": membership.controlling_revision_digest,
                    "uncertainty_lower": interval.lower,
                    "uncertainty_upper": interval.upper,
                }
            )
        )
    evaluation_digest, evaluation_lifecycle, evaluation_status = _chronological_evaluation(
        workspace,
        policy.digest,
        tuple(evaluation_sources),
    )
    unknown_weather_count = sum(item.state.value == "UNKNOWN" for item in t08_evidence.weather)
    replay_payload = {
        "audit_digest": audit.audit_digest,
        "corpus_digest": corpus.digest,
        "evaluation_digest": evaluation_digest,
        "fit_digests": sorted(fit_digests),
        "freeze_digest": freeze.snapshot_manifest_digest,
        "grade_count": grade_count,
        "grade_identity_digest": grade_identity_digest,
        "ingestion_digest": ingestion_report.digest,
        "preference_result_count": preference_result_count,
        "report_digest": _digest(report_text),
        "t08_digest": t08_evidence.digest,
        "t09_state_digests": sorted(state.digest for state in states),
    }
    return RecordedReplayResult(
        corpus_digest=corpus.digest,
        league_keys=corpus.league_keys,
        target_match_count=len(states),
        preference_result_count=preference_result_count,
        grade_count=grade_count,
        research_only=audit.mode.value == "RESEARCH_ONLY",
        production_language=production_language,
        replay_digest=_digest(replay_payload),
        report_digest=_digest(report_text),
        audit_digest=publication.audit_digest,
        export_digest=export.manifest_digest,
        backup_digest=backup.manifest_digest,
        restored_audit_digest=restored_audit.audit_digest,
        evaluation_digest=evaluation_digest,
        evaluation_lifecycle=evaluation_lifecycle,
        evaluation_status=evaluation_status,
        details=MappingProxyType(
            {
                "fallback_imports": ingestion_report.fallback_imports,
                "contextual_conflict_count": contextual_conflict_count,
                "chronological_evaluation_scope": (
                    "STRUCTURAL_FRAMEWORK_SMOKE_WITH_EXPLICIT_RECORDED_TARGET_EXCLUSIONS"
                ),
                "chronological_evaluated_target_count": len(evaluation_sources),
                "chronological_framework_observation_count": 1,
                "chronological_model_unavailable_exclusion_count": (
                    chronological_model_unavailable_exclusion_count
                ),
                "calibration_bundle_statuses": calibration_bundle_statuses,
                "missing_data_inference_count": missing_data_inference_count,
                "missing_corner_void_count": missing_corner_void_count,
                "model_statuses": model_statuses,
                "post_cutoff_appendix_count": len(freeze.appendix),
                "post_cutoff_withdrawal_count": sum(
                    item.disposition.value == "WITHDRAWN" for item in freeze.appendix
                ),
                "prohibited_market_key_count": len(prohibited_market_keys),
                "prohibited_market_keys": prohibited_market_keys,
                "restored_grade_count": len(restored_grades),
                "restored_grade_identity_digest": restored_grade_identity_digest,
                "grade_identity_digest": grade_identity_digest,
                "rejected_preference_count": sum(
                    row.status.value == "REJECT"
                    for match in vetting.matches
                    for row in match.preference_results
                ),
                "settlement_result_counts": {
                    result: sum(
                        grade.settlement_result is not None
                        and grade.settlement_result.value == result
                        for grade in recorded_grades
                    )
                    for result in ("LOSS", "PUSH", "VOID", "WIN")
                },
                "unspecified_identity_count": audit.to_bytes().count(b"UNSPECIFIED"),
                "unknown_weather_count": unknown_weather_count,
                "withdrawn_fixture_count": len(withdrawn_ids),
            }
        ),
    )


__all__ = [
    "REQUIRED_QUALIFICATION_GATES",
    "T19_CORPUS_SCHEMA",
    "T19_QUALIFICATION_SCHEMA",
    "CorpusRights",
    "GateEvidence",
    "GateStatus",
    "QualificationEvidence",
    "QualificationManifest",
    "QualificationStatus",
    "RecordedCorpus",
    "RecordedLeaguePack",
    "RecordedReplayResult",
    "ResourceMeasurement",
    "T19Error",
    "T19ValidationError",
    "measure_recorded_replay",
    "qualify_research_only",
    "run_recorded_replay",
]


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the T19 rights-safe recorded replay.")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--software-commit", default="0" * 40)
    arguments = parser.parse_args()
    corpus = RecordedCorpus.read(arguments.corpus)
    replay, resources = measure_recorded_replay(
        corpus,
        arguments.workspace,
        software_commit=arguments.software_commit,
    )
    payload = {
        "replay": replay.to_dict(),
        "resources": resources.to_dict(),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(_canonical_json(payload) + b"\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not replay.failures() and not resources.failures() else 1


if __name__ == "__main__":
    raise SystemExit(_main())

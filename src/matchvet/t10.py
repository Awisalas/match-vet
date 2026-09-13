"""T10 deterministic settlement grading for the version 1 preference set.

T10 consumes completed, source-backed match records.  It does not predict a
result or alter a frozen Matchweek decision.  A grade is either a terminal
settlement result or a pending investigation state; persistence is handled by
``SettlementGradeRecorder`` below.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast
from uuid import NAMESPACE_URL, uuid5

from matchvet.store import CanonicalIdentifier, Store, StoreTransaction

if TYPE_CHECKING:
    from matchvet.t09 import HistoricalMatch


PREFERENCE_CATALOG_NAME = "matchvet-initial-preference-set"
PREFERENCE_CATALOG_VERSION = "1.0.0"
SETTLEMENT_RULES_NAME = "matchvet-settlement-rules-v1"
SETTLEMENT_RULES_VERSION = "1.0.0"
SOURCE_HIERARCHY_NAME = "matchvet-settlement-source-hierarchy-v1"
SOURCE_HIERARCHY_VERSION = "1.0.0"


class T10Error(Exception):
    """Base error for deterministic T10 grading."""


class T10ValidationError(T10Error, ValueError):
    """The caller supplied an unsupported or malformed T10 value."""


class T10IntegrityError(T10Error):
    """Stored or append-only T10 data does not match its identity."""


class SettlementResult(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"
    VOID = "VOID"


class GradingState(StrEnum):
    PENDING = "PENDING"
    FINAL = "FINAL"


class MatchPhase(StrEnum):
    FULL_MATCH = "FULL_MATCH"
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"


class PreferenceFamily(StrEnum):
    MATCH_WINNER = "Match Winner"
    DOUBLE_CHANCE = "Double Chance"
    MATCH_GOALS_OVER = "Match Goals Over"
    FIRST_HALF_OVER = "First-Half Over"
    SECOND_HALF_OVER = "Second-Half Over"
    HOME_TEAM_GOALS_OVER = "Home Team Goals Over"
    AWAY_TEAM_GOALS_OVER = "Away Team Goals Over"
    CORNER_WINNER = "Corner Match Winner"
    TOTAL_CORNERS_OVER = "Full-Match Total Corners Over"
    HOME_CORNERS_OVER = "Home Team Corners Over"
    AWAY_CORNERS_OVER = "Away Team Corners Over"
    ASIAN_HANDICAP = "Asian Handicap"


class SettlementSource(StrEnum):
    COMPETITION = "COMPETITION"
    FEDERATION = "FEDERATION"
    CLUB = "CLUB"
    FOOTBALL_DATA = "FOOTBALL_DATA"


SOURCE_HIERARCHY: tuple[SettlementSource, ...] = (
    SettlementSource.COMPETITION,
    SettlementSource.FEDERATION,
    SettlementSource.CLUB,
    SettlementSource.FOOTBALL_DATA,
)

SOURCE_AUTHORITY_RANK: Mapping[SettlementSource, int] = MappingProxyType(
    {source: rank for rank, source in enumerate(SOURCE_HIERARCHY)}
)

FULL_GOAL_FACTS = (
    "full_time_home_goals",
    "full_time_away_goals",
)
HALF_GOAL_FACTS = (
    "full_time_home_goals",
    "full_time_away_goals",
    "half_time_home_goals",
    "half_time_away_goals",
)
CORNER_FACTS = ("corners_home", "corners_away")

_COMPLETED_STATUSES = frozenset({"COMPLETED", "COMPLETE", "FINAL", "FINISHED", "PLAYED"})
_PENDING_STATUSES = frozenset(
    {"SCHEDULED", "UNKNOWN", "IN_PROGRESS", "LIVE", "SUSPENDED", "TEMPORARILY_SUSPENDED"}
)
_VOID_STATUSES = frozenset(
    {
        "POSTPONED",
        "CANCELLED",
        "CANCELED",
        "ABANDONED",
        "UNCOMPLETED",
        "FORFEITED",
        "FORFEIT",
        "WALKOVER",
        "AWARDED",
        "ADMIN_AWARDED",
        "ADMINISTRATIVE_AWARD",
        "WITHDRAWN",
        "VOID",
        "REPLAYED",
        "NOT_PLAYED",
    }
)
_PLAYED_ADMIN_STATUSES = frozenset(
    {"FORFEITED", "FORFEIT", "WALKOVER", "AWARDED", "ADMIN_AWARDED", "ADMINISTRATIVE_AWARD"}
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T10ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise T10ValidationError(
            "T10 timestamps must be ISO-8601 values with a UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise T10ValidationError("T10 timestamps must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _optional_utc(value: str | None) -> str | None:
    return _canonical_utc(value) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _immutable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _immutable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_immutable(item) for item in value)
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _jsonable(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise T10ValidationError("T10 identifier lists must be arrays of non-empty strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise T10ValidationError("T10 identifier lists must contain non-empty strings.")
    return tuple(sorted(set(cast(str, item) for item in value)))


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _boolean(value: object, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise T10ValidationError(f"{label} must be boolean.")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _stable_id(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"matchvet:{kind}:{key}"))


def _token(value: object) -> str:
    return " ".join(_text(value, "T10 value").replace("_", " ").replace("-", " ").split()).upper()


def _fraction(value: object, label: str) -> Fraction:
    if isinstance(value, bool):
        raise T10ValidationError(f"{label} must be an exact rational number.")
    if isinstance(value, Fraction):
        selected = value
    elif isinstance(value, int):
        selected = Fraction(value, 1)
    elif isinstance(value, float):
        selected = Fraction(str(value))
    elif isinstance(value, str):
        try:
            selected = Fraction(value.strip())
        except (ValueError, ZeroDivisionError) as error:
            raise T10ValidationError(f"{label} must be an exact rational number.") from error
    else:
        raise T10ValidationError(f"{label} must be an exact rational number.")
    return selected


def _line_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    whole, remainder = divmod(abs(value.numerator), value.denominator)
    sign = "-" if value.numerator < 0 else ""
    return f"{sign}{whole}.{remainder * 10 // value.denominator}"


def _asian_line_text(value: Fraction) -> str:
    text = _line_text(value)
    if value.denominator == 1:
        text = f"{text}.0"
    return f"+{text}" if value > 0 else text


def _line_key(value: Fraction) -> str:
    return _line_text(value).replace("-", "minus_").replace(".", "_")


def _source(value: SettlementSource | str) -> SettlementSource:
    if isinstance(value, SettlementSource):
        return value
    aliases = {
        "COMPETITION": SettlementSource.COMPETITION,
        "LEAGUE": SettlementSource.COMPETITION,
        "OFFICIAL COMPETITION": SettlementSource.COMPETITION,
        "OFFICIAL LEAGUE": SettlementSource.COMPETITION,
        "COMPETITION OR LEAGUE": SettlementSource.COMPETITION,
        "OFFICIAL COMPETITION OR LEAGUE": SettlementSource.COMPETITION,
        "FEDERATION": SettlementSource.FEDERATION,
        "OFFICIAL FEDERATION": SettlementSource.FEDERATION,
        "CLUB": SettlementSource.CLUB,
        "OFFICIAL CLUB": SettlementSource.CLUB,
        "FOOTBALL DATA": SettlementSource.FOOTBALL_DATA,
        "FOOTBALL DATA CO UK": SettlementSource.FOOTBALL_DATA,
        "FOOTBALL DATA CO.UK": SettlementSource.FOOTBALL_DATA,
        "FOOTBALL-DATA": SettlementSource.FOOTBALL_DATA,
        "FOOTBALL-DATA.CO.UK": SettlementSource.FOOTBALL_DATA,
    }
    normalized = _token(value)
    try:
        return aliases[normalized]
    except KeyError as error:
        raise T10ValidationError(
            "Settlement sources must follow competition/league, federation, club, "
            "Football-Data.co.uk hierarchy."
        ) from error


def _family(value: PreferenceFamily | str) -> PreferenceFamily:
    if isinstance(value, PreferenceFamily):
        return value
    aliases = {
        "MATCH WINNER": PreferenceFamily.MATCH_WINNER,
        "DOUBLE CHANCE": PreferenceFamily.DOUBLE_CHANCE,
        "MATCH GOALS OVER": PreferenceFamily.MATCH_GOALS_OVER,
        "MATCH GOALS": PreferenceFamily.MATCH_GOALS_OVER,
        "FIRST HALF OVER": PreferenceFamily.FIRST_HALF_OVER,
        "FIRST HALF GOALS OVER": PreferenceFamily.FIRST_HALF_OVER,
        "SECOND HALF OVER": PreferenceFamily.SECOND_HALF_OVER,
        "SECOND HALF GOALS OVER": PreferenceFamily.SECOND_HALF_OVER,
        "HOME TEAM GOALS OVER": PreferenceFamily.HOME_TEAM_GOALS_OVER,
        "AWAY TEAM GOALS OVER": PreferenceFamily.AWAY_TEAM_GOALS_OVER,
        "CORNER MATCH WINNER": PreferenceFamily.CORNER_WINNER,
        "CORNER WINNER": PreferenceFamily.CORNER_WINNER,
        "FULL MATCH TOTAL CORNERS OVER": PreferenceFamily.TOTAL_CORNERS_OVER,
        "TOTAL CORNERS OVER": PreferenceFamily.TOTAL_CORNERS_OVER,
        "HOME TEAM CORNERS OVER": PreferenceFamily.HOME_CORNERS_OVER,
        "HOME CORNERS OVER": PreferenceFamily.HOME_CORNERS_OVER,
        "AWAY TEAM CORNERS OVER": PreferenceFamily.AWAY_CORNERS_OVER,
        "AWAY CORNERS OVER": PreferenceFamily.AWAY_CORNERS_OVER,
        "ASIAN HANDICAP": PreferenceFamily.ASIAN_HANDICAP,
    }
    normalized = _token(value)
    try:
        return aliases[normalized]
    except KeyError as error:
        raise T10ValidationError(f"Unsupported Betting Preference family: {value!r}.") from error


def _selection(value: object) -> str:
    normalized = _token(value)
    aliases = {
        "HOME": "Home",
        "DRAW": "Draw",
        "AWAY": "Away",
        "OVER": "Over",
        "1X": "1X",
        "X2": "X2",
        "12": "12",
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise T10ValidationError(f"Unsupported Betting Preference selection: {value!r}.") from error


@dataclass(frozen=True)
class BettingPreference:
    """One exact, enabled v1 contract."""

    preference_id: str
    family: PreferenceFamily
    selection: str
    line: Fraction | None
    phase: MatchPhase
    required_facts: tuple[str, ...]
    possible_results: tuple[SettlementResult, ...]
    settlement_rule: str
    label: str
    void_treatment: str = "VOID for final void status or unresolved required evidence."
    source_hierarchy_version: str = SOURCE_HIERARCHY_VERSION

    def __post_init__(self) -> None:
        _text(self.preference_id, "Preference ID")
        selected_family = _family(self.family)
        selected_phase = (
            self.phase if isinstance(self.phase, MatchPhase) else MatchPhase(str(self.phase))
        )
        if self.line is not None and not isinstance(self.line, Fraction):
            raise T10ValidationError("Catalog lines must use exact Fraction values.")
        if not self.required_facts:
            raise T10ValidationError("A Betting Preference must declare required facts.")
        try:
            results = tuple(
                item if isinstance(item, SettlementResult) else SettlementResult(str(item))
                for item in self.possible_results
            )
        except ValueError as error:
            raise T10ValidationError(
                "HALF_WIN and HALF_LOSS and all other outcomes outside WIN, LOSS, or PUSH "
                "are invalid in v1."
            ) from error
        if SettlementResult.VOID in results:
            raise T10ValidationError(
                "VOID is a grading result, not a completed preference outcome."
            )
        if any(item in {"HALF_WIN", "HALF_LOSS"} for item in results):
            raise T10ValidationError("HALF_WIN and HALF_LOSS are invalid in preference set v1.")
        object.__setattr__(self, "family", selected_family)
        object.__setattr__(self, "phase", selected_phase)
        object.__setattr__(self, "selection", _selection(self.selection))
        object.__setattr__(self, "possible_results", results)
        object.__setattr__(self, "required_facts", tuple(self.required_facts))
        _text(self.settlement_rule, "Preference settlement rule")
        _text(self.label, "Preference label")
        _text(self.void_treatment, "Preference VOID treatment")
        hierarchy_version = _text(
            self.source_hierarchy_version, "Preference source hierarchy version"
        )
        if hierarchy_version != SOURCE_HIERARCHY_VERSION:
            raise T10ValidationError(
                "v1 Betting Preferences require the v1 source hierarchy version."
            )
        object.__setattr__(self, "source_hierarchy_version", hierarchy_version)

    def to_dict(self) -> dict[str, object]:
        line = None
        if self.line is not None:
            line = (
                _asian_line_text(self.line)
                if self.family is PreferenceFamily.ASIAN_HANDICAP
                else _line_text(self.line)
            )
        return {
            "family": self.family.value,
            "label": self.label,
            "line": line,
            "phase": self.phase.value,
            "preference_id": self.preference_id,
            "possible_results": tuple(item.value for item in self.possible_results),
            "required_facts": self.required_facts,
            "selection": self.selection,
            "settlement_rule": self.settlement_rule,
            "source_hierarchy_version": self.source_hierarchy_version,
            "void_treatment": self.void_treatment,
        }


@dataclass(frozen=True)
class PreferenceCatalog:
    """An immutable, validated preference catalog."""

    preferences: tuple[BettingPreference, ...]
    version: str = PREFERENCE_CATALOG_VERSION
    name: str = PREFERENCE_CATALOG_NAME
    digest: str = ""

    def __post_init__(self) -> None:
        selected = tuple(self.preferences)
        if len({item.preference_id for item in selected}) != len(selected):
            raise T10ValidationError("Preference IDs must be unique.")
        if any(not isinstance(item, BettingPreference) for item in selected):
            raise T10ValidationError("Preference catalogs contain Betting Preference records only.")
        object.__setattr__(self, "preferences", selected)
        expected = _digest(self._payload())
        if self.digest and self.digest != expected:
            raise T10IntegrityError("Preference catalog digest does not match its contracts.")
        object.__setattr__(self, "digest", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "preferences": [item.to_dict() for item in self.preferences],
            "version": self.version,
        }

    def __iter__(self) -> Iterator[BettingPreference]:
        return iter(self.preferences)

    def __len__(self) -> int:
        return len(self.preferences)

    def get(self, preference_id: str) -> BettingPreference:
        selected = next(
            (
                item
                for item in self.preferences
                if item.preference_id == preference_id or item.label == preference_id
            ),
            None,
        )
        if selected is None:
            raise T10ValidationError(
                f"Unsupported or prohibited Betting Preference: {preference_id!r}."
            )
        return selected

    def resolve(
        self,
        family: PreferenceFamily | str,
        selection: str,
        line: Fraction | int | float | str | None = None,
    ) -> BettingPreference:
        selected_family = _family(family)
        selected_selection = _selection(selection)
        selected_line = None if line is None else _fraction(line, "Preference line")
        for item in self.preferences:
            if (
                item.family is selected_family
                and item.selection == selected_selection
                and item.line == selected_line
            ):
                return item
        line_text = "" if selected_line is None else f" {_line_text(selected_line)}"
        raise T10ValidationError(
            f"Unsupported or prohibited Betting Preference: {selected_family.value} "
            f"{selected_selection}{line_text}."
        )


def _preference(
    preference_id: str,
    family: PreferenceFamily,
    selection: str,
    line: Fraction | None,
    phase: MatchPhase,
    required_facts: tuple[str, ...],
    settlement_rule: str,
    possible_results: tuple[SettlementResult, ...] = (
        SettlementResult.WIN,
        SettlementResult.LOSS,
    ),
) -> BettingPreference:
    line_text = ""
    if line is not None:
        line_text = (
            f" {_asian_line_text(line)}"
            if family is PreferenceFamily.ASIAN_HANDICAP
            else f" {_line_text(line)}"
        )
    return BettingPreference(
        preference_id=preference_id,
        family=family,
        selection=selection,
        line=line,
        phase=phase,
        required_facts=required_facts,
        possible_results=possible_results,
        settlement_rule=settlement_rule,
        label=f"{family.value}: {selection}{line_text}",
    )


def _build_catalog() -> PreferenceCatalog:
    preferences: list[BettingPreference] = []
    for selection in ("Home", "Draw", "Away"):
        preferences.append(
            _preference(
                f"match_winner_{selection.lower()}",
                PreferenceFamily.MATCH_WINNER,
                selection,
                None,
                MatchPhase.FULL_MATCH,
                FULL_GOAL_FACTS,
                "backed result wins the regulation scoreline",
            )
        )
    for selection in ("1X", "X2", "12"):
        preferences.append(
            _preference(
                f"double_chance_{selection.lower()}",
                PreferenceFamily.DOUBLE_CHANCE,
                selection,
                None,
                MatchPhase.FULL_MATCH,
                FULL_GOAL_FACTS,
                "backed double-chance result contains the regulation scoreline",
            )
        )
    for line in (Fraction(3, 2), Fraction(5, 2), Fraction(7, 2)):
        preferences.append(
            _preference(
                f"match_goals_over_{_line_key(line)}",
                PreferenceFamily.MATCH_GOALS_OVER,
                "Over",
                line,
                MatchPhase.FULL_MATCH,
                FULL_GOAL_FACTS,
                "full-match goals exceed the exact half line",
            )
        )
    preferences.extend(
        (
            _preference(
                "first_half_over_1_5",
                PreferenceFamily.FIRST_HALF_OVER,
                "Over",
                Fraction(3, 2),
                MatchPhase.FIRST_HALF,
                HALF_GOAL_FACTS,
                "first-half goals exceed 1.5 including first-half stoppage",
            ),
            _preference(
                "second_half_over_1_5",
                PreferenceFamily.SECOND_HALF_OVER,
                "Over",
                Fraction(3, 2),
                MatchPhase.SECOND_HALF,
                HALF_GOAL_FACTS,
                "second-half goals exceed 1.5 including second-half stoppage",
            ),
        )
    )
    for family, prefix in (
        (PreferenceFamily.HOME_TEAM_GOALS_OVER, "home_team_goals"),
        (PreferenceFamily.AWAY_TEAM_GOALS_OVER, "away_team_goals"),
    ):
        for line in (Fraction(3, 2), Fraction(5, 2)):
            preferences.append(
                _preference(
                    f"{prefix}_over_{_line_key(line)}",
                    family,
                    "Over",
                    line,
                    MatchPhase.FULL_MATCH,
                    FULL_GOAL_FACTS,
                    "named team's full-match goals exceed the exact half line",
                )
            )
    for selection in ("Home", "Draw", "Away"):
        preferences.append(
            _preference(
                f"corner_winner_{selection.lower()}",
                PreferenceFamily.CORNER_WINNER,
                selection,
                None,
                MatchPhase.FULL_MATCH,
                CORNER_FACTS,
                "backed corner count wins the regulation corner scoreline",
            )
        )
    for line in (Fraction(17, 2), Fraction(19, 2), Fraction(21, 2)):
        preferences.append(
            _preference(
                f"total_corners_over_{_line_key(line)}",
                PreferenceFamily.TOTAL_CORNERS_OVER,
                "Over",
                line,
                MatchPhase.FULL_MATCH,
                CORNER_FACTS,
                "combined observed corners exceed the exact half line",
            )
        )
    for family, prefix in (
        (PreferenceFamily.HOME_CORNERS_OVER, "home_corners"),
        (PreferenceFamily.AWAY_CORNERS_OVER, "away_corners"),
    ):
        for line in (Fraction(7, 2), Fraction(9, 2), Fraction(11, 2)):
            preferences.append(
                _preference(
                    f"{prefix}_over_{_line_key(line)}",
                    family,
                    "Over",
                    line,
                    MatchPhase.FULL_MATCH,
                    CORNER_FACTS,
                    "named team's observed corners exceed the exact half line",
                )
            )
    for side in ("Home", "Away"):
        side_prefix = side.lower()
        for line, line_key in (
            (Fraction(0), "0_0"),
            (Fraction(1), "plus_1_0"),
            (Fraction(3, 2), "plus_1_5"),
            (Fraction(-1), "minus_1_0"),
            (Fraction(-3, 2), "minus_1_5"),
        ):
            possible = (
                (SettlementResult.WIN, SettlementResult.PUSH, SettlementResult.LOSS)
                if line.denominator == 1
                else (SettlementResult.WIN, SettlementResult.LOSS)
            )
            preferences.append(
                _preference(
                    f"asian_handicap_{side_prefix}_{line_key}",
                    PreferenceFamily.ASIAN_HANDICAP,
                    side,
                    line,
                    MatchPhase.FULL_MATCH,
                    FULL_GOAL_FACTS,
                    "2 times backed goal difference plus signed line compared with zero",
                    possible,
                )
            )
    return PreferenceCatalog(tuple(preferences))


DEFAULT_PREFERENCE_CATALOG = _build_catalog()
PREFERENCE_CATALOG_V1 = DEFAULT_PREFERENCE_CATALOG
INITIAL_PREFERENCE_SET = DEFAULT_PREFERENCE_CATALOG
PREFERENCE_CATALOG_DIGEST = DEFAULT_PREFERENCE_CATALOG.digest
PREFERENCE_IDS_V1 = tuple(item.preference_id for item in DEFAULT_PREFERENCE_CATALOG)
_PREFERENCE_ID_SET_V1 = frozenset(PREFERENCE_IDS_V1)

# These aliases keep the T10 catalog discoverable alongside the T09 catalog API.
CATALOG_NAME = PREFERENCE_CATALOG_NAME
CATALOG_VERSION = PREFERENCE_CATALOG_VERSION
CATALOG_DIGEST = PREFERENCE_CATALOG_DIGEST
DEFAULT_CATALOG = DEFAULT_PREFERENCE_CATALOG


@dataclass(frozen=True)
class SettlementEvidence:
    """One source-backed record for a Fixture's played result."""

    fixture_id: str
    source_level: SettlementSource | str = SettlementSource.FOOTBALL_DATA
    source_key: str = "football-data"
    record_id: str = ""
    record_set_id: str | None = None
    source_digest: str | None = None
    fixture_status: str = "UNKNOWN"
    regulation_completed: bool | None = None
    resumable: bool = False
    administrative_award: bool = False
    full_time_home_goals: int | None = None
    full_time_away_goals: int | None = None
    half_time_home_goals: int | None = None
    half_time_away_goals: int | None = None
    corners_home: int | None = None
    corners_away: int | None = None
    extra_time_home_goals: int | None = None
    extra_time_away_goals: int | None = None
    shootout_home_goals: int | None = None
    shootout_away_goals: int | None = None
    source_assertion_ids: tuple[str, ...] = ()
    published_at_utc: str | None = None
    observed_at_utc: str | None = None
    retrieved_at_utc: str | None = None
    predecessor_id: str | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        fixture_id = _text(self.fixture_id, "Settlement Evidence fixture ID")
        source_key = _text(self.source_key, "Settlement Evidence source key")
        record_id = (
            _text(self.record_id, "Settlement Evidence record ID")
            if self.record_id
            else f"{fixture_id}:{source_key}"
        )
        source_level = _source(self.source_level)
        status = _text(self.fixture_status, "Settlement Evidence fixture status").upper()
        if self.regulation_completed is not None and not isinstance(
            self.regulation_completed, bool
        ):
            raise T10ValidationError("regulation_completed must be boolean or null.")
        if not isinstance(self.resumable, bool):
            raise T10ValidationError("resumable must be boolean.")
        if not isinstance(self.administrative_award, bool):
            raise T10ValidationError("administrative_award must be boolean.")
        for label, value in (
            ("full-time Home goals", self.full_time_home_goals),
            ("full-time Away goals", self.full_time_away_goals),
            ("half-time Home goals", self.half_time_home_goals),
            ("half-time Away goals", self.half_time_away_goals),
            ("Home corners", self.corners_home),
            ("Away corners", self.corners_away),
            ("extra-time Home goals", self.extra_time_home_goals),
            ("extra-time Away goals", self.extra_time_away_goals),
            ("shootout Home goals", self.shootout_home_goals),
            ("shootout Away goals", self.shootout_away_goals),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise T10ValidationError(f"{label} must be a non-negative integer or null.")
        regulation_completed = self.regulation_completed
        if regulation_completed is None:
            regulation_completed = status in _COMPLETED_STATUSES
        object.__setattr__(self, "fixture_id", fixture_id)
        object.__setattr__(self, "source_level", source_level)
        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "record_id", _text(record_id, "Settlement Evidence record ID"))
        object.__setattr__(
            self,
            "record_set_id",
            _text(self.record_set_id, "Settlement Evidence record set ID")
            if self.record_set_id
            else record_id,
        )
        object.__setattr__(self, "fixture_status", status)
        object.__setattr__(self, "regulation_completed", regulation_completed)
        assertion_ids = _strings(self.source_assertion_ids)
        object.__setattr__(self, "source_assertion_ids", assertion_ids)
        object.__setattr__(self, "published_at_utc", _optional_utc(self.published_at_utc))
        object.__setattr__(self, "observed_at_utc", _optional_utc(self.observed_at_utc))
        object.__setattr__(self, "retrieved_at_utc", _optional_utc(self.retrieved_at_utc))
        if not isinstance(self.provenance, Mapping):
            raise T10ValidationError("Settlement Evidence provenance must be an object.")
        immutable_provenance = _immutable(self.provenance)
        if not isinstance(immutable_provenance, Mapping):
            raise T10ValidationError("Settlement Evidence provenance must be an object.")
        object.__setattr__(self, "provenance", MappingProxyType(dict(immutable_provenance)))
        expected = _digest(self._payload())
        if self.evidence_digest and self.evidence_digest != expected:
            raise T10IntegrityError(
                "Settlement Evidence digest does not match its immutable record."
            )
        object.__setattr__(self, "evidence_digest", expected)

    @property
    def evidence_id(self) -> str:
        return _stable_id("settlement_evidence", self.evidence_digest)

    @property
    def source_rank(self) -> int:
        return SOURCE_AUTHORITY_RANK[cast(SettlementSource, self.source_level)]

    @property
    def status_kind(self) -> str:
        if self.fixture_status in _VOID_STATUSES and (
            self.fixture_status not in _PLAYED_ADMIN_STATUSES
            or self.regulation_completed is not True
        ):
            return "VOID"
        if self.administrative_award and self.regulation_completed is not True:
            return "VOID"
        if self.fixture_status in _PENDING_STATUSES or self.regulation_completed is False:
            return "PENDING"
        if self.regulation_completed is True and (
            self.fixture_status in _COMPLETED_STATUSES
            or self.fixture_status in _PLAYED_ADMIN_STATUSES
        ):
            return "COMPLETE"
        return "PENDING"

    @property
    def invalid_phase_relationship(self) -> bool:
        return (
            self.full_time_home_goals is not None
            and self.half_time_home_goals is not None
            and self.half_time_home_goals > self.full_time_home_goals
        ) or (
            self.full_time_away_goals is not None
            and self.half_time_away_goals is not None
            and self.half_time_away_goals > self.full_time_away_goals
        )

    def complete_for(self, fact_set: tuple[str, ...]) -> bool:
        if self.status_kind != "COMPLETE":
            return False
        if fact_set == FULL_GOAL_FACTS:
            return all(getattr(self, key) is not None for key in FULL_GOAL_FACTS)
        if fact_set == HALF_GOAL_FACTS:
            return not self.invalid_phase_relationship and all(
                getattr(self, key) is not None for key in HALF_GOAL_FACTS
            )
        if fact_set == CORNER_FACTS:
            return all(getattr(self, key) is not None for key in CORNER_FACTS)
        return all(getattr(self, key, None) is not None for key in fact_set)

    def values_for(self, fact_set: tuple[str, ...]) -> tuple[int, ...]:
        values = tuple(getattr(self, key) for key in fact_set)
        if any(value is None for value in values):
            raise T10ValidationError("Incomplete Settlement Evidence has no complete fact tuple.")
        return tuple(cast(int, value) for value in values)

    def _payload(self) -> dict[str, object]:
        return {
            "administrative_award": self.administrative_award,
            "corners_away": self.corners_away,
            "corners_home": self.corners_home,
            "extra_time_away_goals": self.extra_time_away_goals,
            "extra_time_home_goals": self.extra_time_home_goals,
            "fixture_id": self.fixture_id,
            "fixture_status": self.fixture_status,
            "full_time_away_goals": self.full_time_away_goals,
            "full_time_home_goals": self.full_time_home_goals,
            "half_time_away_goals": self.half_time_away_goals,
            "half_time_home_goals": self.half_time_home_goals,
            "predecessor_id": self.predecessor_id,
            "published_at_utc": self.published_at_utc,
            "record_id": self.record_id,
            "record_set_id": self.record_set_id,
            "regulation_completed": self.regulation_completed,
            "resumable": self.resumable,
            "retrieved_at_utc": self.retrieved_at_utc,
            "observed_at_utc": self.observed_at_utc,
            "shootout_away_goals": self.shootout_away_goals,
            "shootout_home_goals": self.shootout_home_goals,
            "source_assertion_ids": self.source_assertion_ids,
            "source_digest": self.source_digest,
            "source_key": self.source_key,
            "source_level": cast(SettlementSource, self.source_level).value,
            "provenance": dict(self.provenance),
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload.update({"evidence_digest": self.evidence_digest, "evidence_id": self.evidence_id})
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SettlementEvidence:
        def integer(*keys: str) -> int | None:
            for key in keys:
                if key in value:
                    raw = value[key]
                    if raw is None:
                        return None
                    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                        raise T10ValidationError(
                            f"Settlement Evidence field {key} must be a non-negative integer "
                            "or null."
                        )
                    return raw
            return None

        source_level = value.get("source_level", value.get("source_authority", "FOOTBALL_DATA"))
        source_key = value.get("source_key", "football-data")
        record_id = value.get("record_id", value.get("source_record_id", ""))
        fixture_status = value.get("fixture_status", value.get("status", "UNKNOWN"))
        evidence = cls(
            fixture_id=_text(value.get("fixture_id"), "Settlement Evidence fixture ID"),
            source_level=cast(str, source_level),
            source_key=cast(str, source_key),
            record_id=cast(str, record_id),
            record_set_id=_optional_text(value.get("record_set_id"), "record_set_id"),
            source_digest=_optional_text(value.get("source_digest"), "source_digest"),
            fixture_status=cast(str, fixture_status),
            regulation_completed=(
                _boolean(value["regulation_completed"], "regulation_completed")
                if value.get("regulation_completed") is not None
                else None
            ),
            resumable=_boolean(value.get("resumable"), "resumable"),
            administrative_award=_boolean(
                value.get("administrative_award"), "administrative_award"
            ),
            full_time_home_goals=integer("full_time_home_goals", "home_goals", "HG"),
            full_time_away_goals=integer("full_time_away_goals", "away_goals", "AG"),
            half_time_home_goals=integer("half_time_home_goals", "H1G"),
            half_time_away_goals=integer("half_time_away_goals", "A1G"),
            corners_home=integer("corners_home", "home_corners", "HC"),
            corners_away=integer("corners_away", "away_corners", "AC"),
            extra_time_home_goals=integer("extra_time_home_goals"),
            extra_time_away_goals=integer("extra_time_away_goals"),
            shootout_home_goals=integer("shootout_home_goals"),
            shootout_away_goals=integer("shootout_away_goals"),
            source_assertion_ids=_strings(value.get("source_assertion_ids", ())),
            published_at_utc=_optional_text(value.get("published_at_utc"), "published_at_utc"),
            observed_at_utc=_optional_text(value.get("observed_at_utc"), "observed_at_utc"),
            retrieved_at_utc=_optional_text(value.get("retrieved_at_utc"), "retrieved_at_utc"),
            predecessor_id=_optional_text(value.get("predecessor_id"), "predecessor_id"),
            provenance=cast(Mapping[str, object], value.get("provenance", {})),
            evidence_digest=str(value.get("evidence_digest", "")),
        )
        evidence_id = value.get("evidence_id")
        if evidence_id is not None and str(evidence_id) != evidence.evidence_id:
            raise T10IntegrityError("Settlement Evidence ID does not match its immutable record.")
        return evidence

    @classmethod
    def from_historical_match(
        cls,
        match: HistoricalMatch,
        *,
        source_level: SettlementSource | str = SettlementSource.FOOTBALL_DATA,
        record_id: str | None = None,
    ) -> SettlementEvidence:
        from matchvet.t09 import HistoricalMatch as T09HistoricalMatch

        if not isinstance(match, T09HistoricalMatch):
            raise T10ValidationError(
                "Settlement Evidence conversion requires a T09 HistoricalMatch."
            )
        metric_names = (
            *FULL_GOAL_FACTS,
            "half_time_home_goals",
            "half_time_away_goals",
            *CORNER_FACTS,
        )

        def observed_metric(name: str) -> int | None:
            value = getattr(match, name)
            return value if match.metric_state(name).value == "OBSERVED" else None

        assertion_ids = {
            *match.source_assertion_ids,
            *(assertion_id for name in metric_names for assertion_id in match.metric_ids(name)),
        }
        return cls(
            fixture_id=match.fixture_id,
            source_level=source_level,
            source_key=match.source_key,
            record_id=record_id or match.fixture_id,
            source_digest=match.source_digest,
            fixture_status=match.fixture_status,
            regulation_completed=(
                (
                    match.final_state.value
                    if isinstance(match.final_state, StrEnum)
                    else str(match.final_state)
                )
                == "OBSERVED"
            ),
            full_time_home_goals=observed_metric("full_time_home_goals"),
            full_time_away_goals=observed_metric("full_time_away_goals"),
            half_time_home_goals=observed_metric("half_time_home_goals"),
            half_time_away_goals=observed_metric("half_time_away_goals"),
            corners_home=observed_metric("corners_home"),
            corners_away=observed_metric("corners_away"),
            source_assertion_ids=tuple(sorted(assertion_ids)),
            observed_at_utc=match.observed_at_utc,
            published_at_utc=match.published_at_utc,
            provenance={
                "origin_id": match.origin_id,
                "source_key": match.source_key,
                "source_digest": match.source_digest,
                "source_assertion_ids": match.source_assertion_ids,
                "fixture_status": match.fixture_status,
                "historical_match": match.to_dict(),
                "metric_input_ids": dict(match.metric_input_ids),
                "metric_states": {name: match.metric_state(name).value for name in metric_names},
            },
        )


def _coerce_evidence(value: object) -> SettlementEvidence:
    if isinstance(value, SettlementEvidence):
        return value
    if isinstance(value, Mapping):
        return SettlementEvidence.from_mapping(value)
    try:
        from matchvet.t09 import HistoricalMatch

        if isinstance(value, HistoricalMatch):
            return SettlementEvidence.from_historical_match(value)
    except ImportError:
        pass
    raise T10ValidationError("Settlement grading requires SettlementEvidence records.")


@dataclass(frozen=True)
class FrozenRecommendation:
    """The immutable prediction references retained beside a later grade."""

    recommendation_id: str
    fixture_id: str
    preference_id: str
    matchweek_id: str = ""
    prediction_digest: str | None = None
    frozen_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recommendation_id", _text(self.recommendation_id, "Recommendation ID")
        )
        object.__setattr__(self, "fixture_id", _text(self.fixture_id, "Recommendation fixture ID"))
        object.__setattr__(
            self, "preference_id", _text(self.preference_id, "Recommendation preference ID")
        )
        if self.matchweek_id:
            object.__setattr__(
                self, "matchweek_id", _text(self.matchweek_id, "Recommendation Matchweek ID")
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "frozen_evidence_digest": self.frozen_evidence_digest,
            "matchweek_id": self.matchweek_id,
            "preference_id": self.preference_id,
            "prediction_digest": self.prediction_digest,
            "recommendation_id": self.recommendation_id,
        }


@dataclass(frozen=True)
class _EvidenceGroup:
    source_level: SettlementSource
    source_key: str
    record_set_id: str
    records: tuple[SettlementEvidence, ...]
    first_index: int

    @property
    def source_rank(self) -> int:
        return SOURCE_AUTHORITY_RANK[self.source_level]

    @property
    def status_kinds(self) -> frozenset[str]:
        return frozenset(item.status_kind for item in self.records)

    @property
    def status_conflict(self) -> bool:
        return len(self.status_kinds) > 1

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.records)

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(item.record_id for item in self.records)

    def _value(self, field_name: str) -> tuple[int | None, bool]:
        values = {
            getattr(item, field_name)
            for item in self.records
            if getattr(item, field_name) is not None
        }
        if len(values) > 1:
            return None, True
        return (next(iter(values)) if values else None), False

    def complete_for(self, fact_set: tuple[str, ...]) -> bool:
        if self.status_conflict or self.status_kinds != {"COMPLETE"}:
            return False
        values: dict[str, int] = {}
        for fact in fact_set:
            value, conflict = self._value(fact)
            if conflict or value is None:
                return False
            values[fact] = value
        if fact_set == HALF_GOAL_FACTS:
            if values["half_time_home_goals"] > values["full_time_home_goals"]:
                return False
            if values["half_time_away_goals"] > values["full_time_away_goals"]:
                return False
        return True

    def conflicts_for(self, fact_set: tuple[str, ...]) -> bool:
        if self.status_conflict or self.status_kinds != {"COMPLETE"}:
            return False
        return any(self._value(fact)[1] for fact in fact_set)

    def values_for(self, fact_set: tuple[str, ...]) -> tuple[int, ...]:
        if not self.complete_for(fact_set):
            raise T10ValidationError("An incomplete or conflicting evidence group has no values.")
        return tuple(cast(int, self._value(fact)[0]) for fact in fact_set)

    def signature(self, fact_set: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(self._value(fact)[0] for fact in fact_set)


def _evidence_groups(evidence: Sequence[SettlementEvidence]) -> tuple[_EvidenceGroup, ...]:
    grouped: dict[tuple[SettlementSource, str, str], list[tuple[int, SettlementEvidence]]] = {}
    for index, item in enumerate(evidence):
        key = (
            cast(SettlementSource, item.source_level),
            item.source_key,
            cast(str, item.record_set_id),
        )
        grouped.setdefault(key, []).append((index, item))
    groups = [
        _EvidenceGroup(
            source_level=key[0],
            source_key=key[1],
            record_set_id=key[2],
            records=tuple(item for _, item in values),
            first_index=min(index for index, _ in values),
        )
        for key, values in grouped.items()
    ]
    return tuple(
        sorted(
            groups,
            key=lambda item: (item.source_rank, item.source_key, item.record_set_id),
        )
    )


def _active_evidence_records(
    evidence: Sequence[SettlementEvidence],
) -> tuple[tuple[SettlementEvidence, ...], tuple[SettlementEvidence, ...]]:
    """Exclude records explicitly superseded by an evidence successor."""
    by_evidence_id = {item.evidence_id: item for item in evidence}
    by_record_id = {item.record_id: item for item in evidence}
    predecessor_ids = {item.predecessor_id for item in evidence if item.predecessor_id is not None}
    superseded_ids = {
        candidate.evidence_id
        for predecessor_id in predecessor_ids
        for candidate in (
            by_evidence_id.get(predecessor_id),
            by_record_id.get(predecessor_id),
        )
        if candidate is not None
    }
    active = tuple(item for item in evidence if item.evidence_id not in superseded_ids)
    superseded = tuple(item for item in evidence if item.evidence_id in superseded_ids)
    return active, superseded


def _aggregate_evidence_digest(evidence: Sequence[SettlementEvidence]) -> str:
    return _digest({"evidence_digests": tuple(sorted(item.evidence_digest for item in evidence))})


def _status_group(groups: Sequence[_EvidenceGroup]) -> tuple[_EvidenceGroup | None, bool]:
    if not groups:
        return None, False
    first_rank = min(item.source_rank for item in groups)
    highest = tuple(item for item in groups if item.source_rank == first_rank)
    kinds = {kind for item in highest for kind in item.status_kinds}
    if len(kinds) > 1:
        return None, True
    return highest[0], False


def _fact_group(
    groups: Sequence[_EvidenceGroup], fact_set: tuple[str, ...]
) -> tuple[_EvidenceGroup | None, bool, tuple[_EvidenceGroup, ...]]:
    complete = tuple(item for item in groups if item.complete_for(fact_set))
    if complete:
        first_rank = min(item.source_rank for item in complete)
        blocking_conflicts = tuple(
            item
            for item in groups
            if item.source_rank <= first_rank and item.conflicts_for(fact_set)
        )
        if blocking_conflicts:
            conflict_rank = min(item.source_rank for item in blocking_conflicts)
            return (
                None,
                True,
                tuple(item for item in blocking_conflicts if item.source_rank == conflict_rank),
            )
        same_rank = tuple(item for item in complete if item.source_rank == first_rank)
        signatures = {item.signature(fact_set) for item in same_rank}
        if len(signatures) > 1:
            return None, True, same_rank
        selected = same_rank[0]
        overridden = tuple(
            item
            for item in groups
            if item.source_rank > first_rank
            and (item.complete_for(fact_set) or item.conflicts_for(fact_set))
        )
        return selected, False, overridden
    conflicts = tuple(item for item in groups if item.conflicts_for(fact_set))
    if conflicts:
        first_rank = min(item.source_rank for item in conflicts)
        controlling = tuple(item for item in conflicts if item.source_rank == first_rank)
        return None, True, controlling
    return None, False, ()


def _required_fact_set(preference: BettingPreference) -> tuple[str, ...]:
    return preference.required_facts


def _over_result(value: int, line: Fraction) -> SettlementResult:
    left = 2 * value
    right = line * 2
    if right.denominator != 1:
        raise T10IntegrityError("v1 Over settlement lines must be representable in half-units.")
    right_integer = right.numerator
    if left > right_integer:
        return SettlementResult.WIN
    if left < right_integer:
        return SettlementResult.LOSS
    raise T10IntegrityError("An enabled v1 .5 Over line cannot settle at equality.")


def _settle_preference(preference: BettingPreference, group: _EvidenceGroup) -> SettlementResult:
    family = preference.family
    if family in {
        PreferenceFamily.MATCH_WINNER,
        PreferenceFamily.DOUBLE_CHANCE,
        PreferenceFamily.ASIAN_HANDICAP,
    }:
        home_goals, away_goals = group.values_for(FULL_GOAL_FACTS)
        if family is PreferenceFamily.MATCH_WINNER:
            selected = (
                home_goals > away_goals
                if preference.selection == "Home"
                else away_goals > home_goals
                if preference.selection == "Away"
                else home_goals == away_goals
            )
            return SettlementResult.WIN if selected else SettlementResult.LOSS
        if family is PreferenceFamily.DOUBLE_CHANCE:
            selected = (
                home_goals >= away_goals
                if preference.selection == "1X"
                else away_goals >= home_goals
                if preference.selection == "X2"
                else home_goals != away_goals
            )
            return SettlementResult.WIN if selected else SettlementResult.LOSS
        assert preference.line is not None
        backed_difference = (
            home_goals - away_goals if preference.selection == "Home" else away_goals - home_goals
        )
        adjusted_margin = 2 * backed_difference + preference.line * 2
        if adjusted_margin > 0:
            return SettlementResult.WIN
        if adjusted_margin == 0:
            return SettlementResult.PUSH
        return SettlementResult.LOSS

    if family is PreferenceFamily.FIRST_HALF_OVER or family is PreferenceFamily.SECOND_HALF_OVER:
        home_goals, away_goals, home_half, away_half = group.values_for(HALF_GOAL_FACTS)
        value = home_half + away_half
        if family is PreferenceFamily.SECOND_HALF_OVER:
            value = home_goals - home_half + away_goals - away_half
        assert preference.line is not None
        return _over_result(value, preference.line)

    if family is PreferenceFamily.MATCH_GOALS_OVER:
        home_goals, away_goals = group.values_for(FULL_GOAL_FACTS)
        assert preference.line is not None
        return _over_result(home_goals + away_goals, preference.line)

    if family is PreferenceFamily.HOME_TEAM_GOALS_OVER:
        value = group.values_for(FULL_GOAL_FACTS)[0]
        assert preference.line is not None
        return _over_result(value, preference.line)

    if family is PreferenceFamily.AWAY_TEAM_GOALS_OVER:
        value = group.values_for(FULL_GOAL_FACTS)[1]
        assert preference.line is not None
        return _over_result(value, preference.line)

    home_corners, away_corners = group.values_for(CORNER_FACTS)
    if family is PreferenceFamily.CORNER_WINNER:
        selected = (
            home_corners > away_corners
            if preference.selection == "Home"
            else away_corners > home_corners
            if preference.selection == "Away"
            else home_corners == away_corners
        )
        return SettlementResult.WIN if selected else SettlementResult.LOSS
    if family is PreferenceFamily.TOTAL_CORNERS_OVER:
        assert preference.line is not None
        return _over_result(home_corners + away_corners, preference.line)
    assert preference.line is not None
    value = home_corners if family is PreferenceFamily.HOME_CORNERS_OVER else away_corners
    return _over_result(value, preference.line)


@dataclass(frozen=True)
class SettlementGrade:
    """The result of grading one exact preference against one Fixture."""

    fixture_id: str
    preference: BettingPreference
    grading_state: GradingState
    settlement_result: SettlementResult | None
    reason_code: str
    reason: str
    evidence_digest: str
    evidence_ids: tuple[str, ...]
    selected_evidence_set_id: str | None
    selected_source_level: SettlementSource | None
    selected_source_key: str | None
    selected_source_record_ids: tuple[str, ...]
    provenance: Mapping[str, object]
    evidence: tuple[SettlementEvidence, ...] = ()
    matchweek_id: str = ""
    recommendation_id: str = ""
    prediction_digest: str | None = None
    frozen_evidence_digest: str | None = None
    predecessor_grade_id: str | None = None
    correction_sequence: int = 0
    grade_id: str = ""
    grade_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.preference, BettingPreference):
            raise T10ValidationError("Settlement Grades require a Betting Preference.")
        try:
            state = (
                self.grading_state
                if isinstance(self.grading_state, GradingState)
                else GradingState(str(self.grading_state))
            )
            result = (
                self.settlement_result
                if self.settlement_result is None
                or isinstance(self.settlement_result, SettlementResult)
                else SettlementResult(str(self.settlement_result))
            )
        except ValueError as error:
            raise T10ValidationError(
                "Settlement Grades use PENDING or FINAL and WIN, LOSS, PUSH, or VOID."
            ) from error
        if state is GradingState.PENDING and result is not None:
            raise T10ValidationError("Pending grading has no Settlement Result.")
        if state is GradingState.FINAL and result is None:
            raise T10ValidationError("Final grading requires WIN, LOSS, PUSH, or VOID.")
        if (
            isinstance(self.correction_sequence, bool)
            or not isinstance(self.correction_sequence, int)
            or self.correction_sequence < 0
        ):
            raise T10ValidationError("Correction sequence must not be negative.")
        object.__setattr__(
            self, "fixture_id", _text(self.fixture_id, "Settlement Grade fixture ID")
        )
        object.__setattr__(self, "grading_state", state)
        object.__setattr__(self, "settlement_result", result)
        evidence = tuple(self.evidence)
        if not all(isinstance(item, SettlementEvidence) for item in evidence):
            raise T10ValidationError("Settlement Grades require Settlement Evidence records.")
        evidence_ids = tuple(sorted(item.evidence_id for item in evidence))
        supplied_evidence_ids = tuple(sorted(set(self.evidence_ids)))
        if supplied_evidence_ids != evidence_ids:
            raise T10IntegrityError("Settlement Grade evidence IDs do not match its evidence.")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(
            self, "selected_source_record_ids", tuple(sorted(set(self.selected_source_record_ids)))
        )
        object.__setattr__(
            self,
            "selected_source_level",
            _source(self.selected_source_level) if self.selected_source_level is not None else None,
        )
        if not isinstance(self.provenance, Mapping):
            raise T10ValidationError("Settlement Grade provenance must be an object.")
        immutable_provenance = _immutable(self.provenance)
        if not isinstance(immutable_provenance, Mapping):
            raise T10ValidationError("Settlement Grade provenance must be an object.")
        object.__setattr__(self, "provenance", MappingProxyType(dict(immutable_provenance)))
        object.__setattr__(self, "evidence", evidence)
        expected_evidence_digest = _aggregate_evidence_digest(evidence)
        if self.evidence_digest and self.evidence_digest != expected_evidence_digest:
            raise T10IntegrityError("Settlement Grade evidence digest does not match its evidence.")
        object.__setattr__(self, "evidence_digest", expected_evidence_digest)
        payload = self._payload(include_identity=False)
        expected_digest = _digest(payload)
        if self.grade_digest and self.grade_digest != expected_digest:
            raise T10IntegrityError("Settlement Grade digest does not match its immutable fields.")
        object.__setattr__(self, "grade_digest", expected_digest)
        expected_grade_id = _stable_id("settlement_grade", f"{self.grading_key}:{expected_digest}")
        if self.grade_id and self.grade_id != expected_grade_id:
            raise T10IntegrityError("Settlement Grade ID does not match its immutable fields.")
        if not self.grade_id:
            object.__setattr__(
                self,
                "grade_id",
                expected_grade_id,
            )

    @property
    def grading_key(self) -> str:
        return "|".join(
            (
                self.fixture_id,
                self.matchweek_id,
                self.recommendation_id,
                self.preference.preference_id,
            )
        )

    @property
    def result(self) -> SettlementResult | None:
        return self.settlement_result

    @property
    def status(self) -> GradingState:
        return self.grading_state

    @property
    def is_pending(self) -> bool:
        return self.grading_state is GradingState.PENDING

    @property
    def source_authority(self) -> str | None:
        return self.selected_source_level.value if self.selected_source_level is not None else None

    def _payload(self, *, include_identity: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_digest": self.evidence_digest,
            "evidence_ids": self.evidence_ids,
            "fixture_id": self.fixture_id,
            "frozen_evidence_digest": self.frozen_evidence_digest,
            "grading_state": self.grading_state.value,
            "matchweek_id": self.matchweek_id,
            "preference": self.preference.to_dict(),
            "predecessor_grade_id": self.predecessor_grade_id,
            "prediction_digest": self.prediction_digest,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "recommendation_id": self.recommendation_id,
            "selected_evidence_set_id": self.selected_evidence_set_id,
            "selected_source_key": self.selected_source_key,
            "selected_source_level": (
                self.selected_source_level.value if self.selected_source_level is not None else None
            ),
            "selected_source_record_ids": self.selected_source_record_ids,
            "settlement_result": (
                self.settlement_result.value if self.settlement_result is not None else None
            ),
        }
        if include_identity:
            payload.update(
                {
                    "correction_sequence": self.correction_sequence,
                    "grade_digest": self.grade_digest,
                    "grade_id": self.grade_id,
                    "provenance": dict(self.provenance),
                }
            )
        else:
            payload["provenance"] = dict(self.provenance)
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._payload(include_identity=True)

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object], catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG
    ) -> SettlementGrade:
        preference_value = value.get("preference")
        preference_id = (
            str(preference_value.get("preference_id"))
            if isinstance(preference_value, Mapping)
            and preference_value.get("preference_id") is not None
            else str(value.get("preference_id", ""))
        )
        preference = catalog.get(preference_id)
        evidence_raw = value.get("evidence", ())
        if not isinstance(evidence_raw, (tuple, list)) or not all(
            isinstance(item, Mapping) for item in evidence_raw
        ):
            raise T10ValidationError(
                "Stored Settlement Grade evidence must be an array of objects."
            )
        evidence = tuple(SettlementEvidence.from_mapping(item) for item in evidence_raw)
        selected_source = value.get("selected_source_level")
        provenance = value.get("provenance", {})
        if not isinstance(provenance, Mapping):
            raise T10ValidationError("Stored Settlement Grade provenance must be an object.")
        return cls(
            fixture_id=_text(value.get("fixture_id"), "Stored Settlement Grade fixture ID"),
            preference=preference,
            grading_state=GradingState(str(value.get("grading_state", "PENDING"))),
            settlement_result=(
                SettlementResult(str(value["settlement_result"]))
                if value.get("settlement_result") is not None
                else None
            ),
            reason_code=str(value.get("reason_code", "")),
            reason=str(value.get("reason", "")),
            evidence_digest=str(value.get("evidence_digest", "")),
            evidence_ids=_strings(value.get("evidence_ids", ())),
            selected_evidence_set_id=(
                str(value["selected_evidence_set_id"])
                if value.get("selected_evidence_set_id") is not None
                else None
            ),
            selected_source_level=_source(str(selected_source))
            if selected_source is not None
            else None,
            selected_source_key=(
                str(value["selected_source_key"])
                if value.get("selected_source_key") is not None
                else None
            ),
            selected_source_record_ids=_strings(value.get("selected_source_record_ids", ())),
            provenance=cast(Mapping[str, object], provenance),
            evidence=evidence,
            matchweek_id=str(value.get("matchweek_id", "")),
            recommendation_id=str(value.get("recommendation_id", "")),
            prediction_digest=(
                str(value["prediction_digest"])
                if value.get("prediction_digest") is not None
                else None
            ),
            frozen_evidence_digest=(
                str(value["frozen_evidence_digest"])
                if value.get("frozen_evidence_digest") is not None
                else None
            ),
            predecessor_grade_id=(
                str(value["predecessor_grade_id"])
                if value.get("predecessor_grade_id") is not None
                else None
            ),
            correction_sequence=_int_value(value.get("correction_sequence", 0)),
            grade_id=str(value.get("grade_id", "")),
            grade_digest=str(value.get("grade_digest", "")),
        )


class SettlementGrader:
    """Grade one preference or the complete v1 catalog without writing state."""

    def __init__(self, catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG) -> None:
        if (
            catalog.name != PREFERENCE_CATALOG_NAME
            or catalog.version != PREFERENCE_CATALOG_VERSION
            or len(catalog) != 37
            or frozenset(item.preference_id for item in catalog) != _PREFERENCE_ID_SET_V1
            or catalog.digest != PREFERENCE_CATALOG_DIGEST
        ):
            raise T10ValidationError(
                "T10 grading requires the exact 37-contract preference catalog v1."
            )
        self.catalog = catalog

    def _preference(self, value: BettingPreference | str) -> BettingPreference:
        if isinstance(value, BettingPreference):
            return self.catalog.get(value.preference_id)
        return self.catalog.get(value)

    def grade(
        self,
        preference: BettingPreference | str,
        evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
        *,
        fixture_id: str | None = None,
        finalize: bool = False,
        close_unresolved: bool | None = None,
        withdrawn: bool = False,
        matchweek_id: str = "",
        recommendation_id: str = "",
        prediction_digest: str | None = None,
        frozen_evidence_digest: str | None = None,
        frozen_recommendation: FrozenRecommendation | None = None,
    ) -> SettlementGrade:
        if close_unresolved is not None:
            finalize = close_unresolved
        selected_preference = self._preference(preference)
        if frozen_recommendation is not None:
            if frozen_recommendation.preference_id != selected_preference.preference_id:
                raise T10ValidationError(
                    "Frozen Recommendation preference does not match the grade."
                )
            if fixture_id is not None and fixture_id != frozen_recommendation.fixture_id:
                raise T10ValidationError("Frozen Recommendation fixture does not match the grade.")
            fixture_id = frozen_recommendation.fixture_id
            matchweek_id = frozen_recommendation.matchweek_id
            recommendation_id = frozen_recommendation.recommendation_id
            prediction_digest = frozen_recommendation.prediction_digest
            frozen_evidence_digest = frozen_recommendation.frozen_evidence_digest
        records = tuple(
            sorted(
                (_coerce_evidence(item) for item in evidence),
                key=lambda item: (
                    item.source_rank,
                    item.source_key,
                    cast(str, item.record_set_id),
                    item.record_id,
                    item.evidence_digest,
                ),
            )
        )
        if fixture_id is None:
            if not records:
                raise T10ValidationError("An empty evidence set requires a fixture_id.")
            fixture_id = records[0].fixture_id
        selected_fixture_id = _text(fixture_id, "Settlement Grade fixture ID")
        if any(item.fixture_id != selected_fixture_id for item in records):
            raise T10ValidationError("All Settlement Evidence must identify the same Fixture.")
        evidence_ids = tuple(item.evidence_id for item in records)
        evidence_digest = _aggregate_evidence_digest(records)
        active_records, superseded_records = _active_evidence_records(records)
        groups = _evidence_groups(active_records)
        provenance: dict[str, object] = {
            "considered_evidence": [item.to_dict() for item in records],
            "rules_name": SETTLEMENT_RULES_NAME,
            "rules_version": SETTLEMENT_RULES_VERSION,
            "source_hierarchy_name": SOURCE_HIERARCHY_NAME,
            "source_hierarchy_version": SOURCE_HIERARCHY_VERSION,
            "source_hierarchy": tuple(item.value for item in SOURCE_HIERARCHY),
            "superseded_evidence": [item.to_dict() for item in superseded_records],
        }

        def unresolved(
            reason_code: str, reason: str, *, conflict_groups: Sequence[_EvidenceGroup] = ()
        ) -> SettlementGrade:
            provenance["conflict_evidence_ids"] = tuple(
                evidence_id for group in conflict_groups for evidence_id in group.evidence_ids
            )
            return SettlementGrade(
                fixture_id=selected_fixture_id,
                preference=selected_preference,
                grading_state=GradingState.FINAL if finalize else GradingState.PENDING,
                settlement_result=SettlementResult.VOID if finalize else None,
                reason_code=reason_code,
                reason=(f"{reason} Grading closed unresolved." if finalize else reason),
                evidence_digest=evidence_digest,
                evidence_ids=evidence_ids,
                selected_evidence_set_id=None,
                selected_source_level=None,
                selected_source_key=None,
                selected_source_record_ids=(),
                provenance=provenance,
                evidence=records,
                matchweek_id=matchweek_id,
                recommendation_id=recommendation_id,
                prediction_digest=prediction_digest,
                frozen_evidence_digest=frozen_evidence_digest,
            )

        if withdrawn:
            return SettlementGrade(
                fixture_id=selected_fixture_id,
                preference=selected_preference,
                grading_state=GradingState.FINAL,
                settlement_result=SettlementResult.VOID,
                reason_code="WITHDRAWN_RECOMMENDATION",
                reason=(
                    "The frozen Matchweek recommendation was withdrawn after postponement "
                    "or cancellation."
                ),
                evidence_digest=evidence_digest,
                evidence_ids=evidence_ids,
                selected_evidence_set_id=None,
                selected_source_level=None,
                selected_source_key=None,
                selected_source_record_ids=(),
                provenance=provenance,
                evidence=records,
                matchweek_id=matchweek_id,
                recommendation_id=recommendation_id,
                prediction_digest=prediction_digest,
                frozen_evidence_digest=frozen_evidence_digest,
            )

        status, status_conflict = _status_group(groups)
        if status_conflict:
            return unresolved(
                "SOURCE_CONFLICT",
                "The highest-authority source level contains conflicting fixture statuses.",
                conflict_groups=tuple(
                    item
                    for item in groups
                    if item.source_rank == min(group.source_rank for group in groups)
                ),
            )
        if status is None:
            return unresolved("MISSING_FIXTURE_STATUS", "No complete fixture status was supplied.")
        provenance["status_source"] = {
            "source_level": status.source_level.value,
            "source_key": status.source_key,
            "record_ids": status.record_ids,
            "status": tuple(sorted(status.status_kinds)),
        }
        if status.status_kinds == {"VOID"}:
            return SettlementGrade(
                fixture_id=selected_fixture_id,
                preference=selected_preference,
                grading_state=GradingState.FINAL,
                settlement_result=SettlementResult.VOID,
                reason_code="VOID_FIXTURE_STATUS",
                reason=(
                    f"Fixture status {status.records[0].fixture_status} is a settled VOID "
                    "condition."
                ),
                evidence_digest=evidence_digest,
                evidence_ids=evidence_ids,
                selected_evidence_set_id=None,
                selected_source_level=status.source_level,
                selected_source_key=status.source_key,
                selected_source_record_ids=status.record_ids,
                provenance=provenance,
                evidence=records,
                matchweek_id=matchweek_id,
                recommendation_id=recommendation_id,
                prediction_digest=prediction_digest,
                frozen_evidence_digest=frozen_evidence_digest,
            )
        if status.status_kinds != {"COMPLETE"}:
            return unresolved(
                "PENDING_FIXTURE_STATUS",
                "The fixture is not complete. A resumable suspension remains pending.",
            )

        selected, conflict, related = _fact_group(groups, _required_fact_set(selected_preference))
        if conflict:
            return unresolved(
                "SOURCE_CONFLICT",
                "Complete records at the controlling source level disagree on required facts.",
                conflict_groups=related,
            )
        if selected is None:
            reason_code = (
                "INVALID_PHASE_RELATIONSHIP"
                if any(item.invalid_phase_relationship for item in records)
                else "MISSING_REQUIRED_FACTS"
            )
            return unresolved(
                reason_code, "No complete authoritative record contains the required facts."
            )
        provenance["selected_evidence"] = [item.to_dict() for item in selected.records]
        provenance["overridden_evidence"] = [
            item.to_dict() for group in related for item in group.records
        ]
        try:
            result = _settle_preference(selected_preference, selected)
        except T10ValidationError:
            return unresolved(
                "INVALID_PHASE_RELATIONSHIP", "Required phase facts are contradictory."
            )
        return SettlementGrade(
            fixture_id=selected_fixture_id,
            preference=selected_preference,
            grading_state=GradingState.FINAL,
            settlement_result=result,
            reason_code="GRADED",
            reason=(
                "The first complete applicable record in the fixed source hierarchy "
                "controls grading."
            ),
            evidence_digest=evidence_digest,
            evidence_ids=evidence_ids,
            selected_evidence_set_id=selected.records[0].evidence_id,
            selected_source_level=selected.source_level,
            selected_source_key=selected.source_key,
            selected_source_record_ids=selected.record_ids,
            provenance=provenance,
            evidence=records,
            matchweek_id=matchweek_id,
            recommendation_id=recommendation_id,
            prediction_digest=prediction_digest,
            frozen_evidence_digest=frozen_evidence_digest,
        )

    def grade_all(
        self,
        evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
        *,
        fixture_id: str | None = None,
        finalize: bool = False,
        close_unresolved: bool | None = None,
        withdrawn: bool = False,
        matchweek_id: str = "",
        recommendation_ids: Mapping[str, str] | None = None,
        prediction_digests: Mapping[str, str] | None = None,
        frozen_evidence_digest: str | None = None,
    ) -> tuple[SettlementGrade, ...]:
        records = tuple(_coerce_evidence(item) for item in evidence)
        return tuple(
            self.grade(
                preference,
                records,
                fixture_id=fixture_id,
                finalize=finalize,
                close_unresolved=close_unresolved,
                withdrawn=withdrawn,
                matchweek_id=matchweek_id,
                recommendation_id=(recommendation_ids or {}).get(preference.preference_id, ""),
                prediction_digest=(prediction_digests or {}).get(preference.preference_id),
                frozen_evidence_digest=frozen_evidence_digest,
            )
            for preference in self.catalog
        )


def grade_preference(
    preference: BettingPreference | str,
    evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
    *,
    fixture_id: str | None = None,
    finalize: bool = False,
    close_unresolved: bool | None = None,
    withdrawn: bool = False,
    matchweek_id: str = "",
    recommendation_id: str = "",
    prediction_digest: str | None = None,
    frozen_evidence_digest: str | None = None,
    frozen_recommendation: FrozenRecommendation | None = None,
) -> SettlementGrade:
    """Convenience function for the public pure grading seam."""
    return SettlementGrader().grade(
        preference,
        evidence,
        fixture_id=fixture_id,
        finalize=finalize,
        close_unresolved=close_unresolved,
        withdrawn=withdrawn,
        matchweek_id=matchweek_id,
        recommendation_id=recommendation_id,
        prediction_digest=prediction_digest,
        frozen_evidence_digest=frozen_evidence_digest,
        frozen_recommendation=frozen_recommendation,
    )


def grade_all_preferences(
    evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
    *,
    fixture_id: str | None = None,
    finalize: bool = False,
    close_unresolved: bool | None = None,
    withdrawn: bool = False,
    matchweek_id: str = "",
    recommendation_ids: Mapping[str, str] | None = None,
    prediction_digests: Mapping[str, str] | None = None,
    frozen_evidence_digest: str | None = None,
) -> tuple[SettlementGrade, ...]:
    """Grade every exact v1 preference in catalog order."""
    return SettlementGrader().grade_all(
        evidence,
        fixture_id=fixture_id,
        finalize=finalize,
        close_unresolved=close_unresolved,
        withdrawn=withdrawn,
        matchweek_id=matchweek_id,
        recommendation_ids=recommendation_ids,
        prediction_digests=prediction_digests,
        frozen_evidence_digest=frozen_evidence_digest,
    )


T10Grader = SettlementGrader
T10SettlementGrader = SettlementGrader


def _stored_evidence_from_row(row: Sequence[object]) -> SettlementEvidence:
    try:
        payload = json.loads(str(row[7]))
    except json.JSONDecodeError as error:
        raise T10IntegrityError("Stored Settlement Evidence payload is malformed.") from error
    if not isinstance(payload, Mapping):
        raise T10IntegrityError("Stored Settlement Evidence payload is not an object.")
    evidence = SettlementEvidence.from_mapping(cast(Mapping[str, object], payload))
    expected = (
        evidence.evidence_id,
        evidence.fixture_id,
        cast(SettlementSource, evidence.source_level).value,
        evidence.source_key,
        evidence.record_id,
        evidence.record_set_id,
        evidence.evidence_digest,
    )
    actual = tuple(str(row[index]) for index in range(7))
    if actual != expected:
        raise T10IntegrityError("Stored Settlement Evidence columns do not match its payload.")
    return evidence


def _stored_grade_from_row(
    connection: Any,
    row: Sequence[object],
    *,
    expected_grading_key: str | None = None,
) -> SettlementGrade:
    try:
        payload = json.loads(str(row[15]))
    except json.JSONDecodeError as error:
        raise T10IntegrityError("Stored Settlement Grade payload is malformed.") from error
    if not isinstance(payload, Mapping):
        raise T10IntegrityError("Stored Settlement Grade payload is not an object.")
    grade = SettlementGrade.from_dict(cast(Mapping[str, object], payload))
    expected = (
        grade.grade_id,
        grade.fixture_id,
        grade.preference.preference_id,
        grade.matchweek_id,
        grade.recommendation_id,
        grade.grading_state.value,
        grade.settlement_result.value if grade.settlement_result is not None else None,
        grade.reason_code,
        grade.reason,
        grade.evidence_digest,
        grade.prediction_digest,
        grade.frozen_evidence_digest,
        grade.correction_sequence,
        grade.predecessor_grade_id,
        grade.grade_digest,
    )
    actual = tuple(row[index] for index in range(15))
    if actual != expected:
        raise T10IntegrityError("Stored Settlement Grade columns do not match its payload.")
    if expected_grading_key is not None and str(row[16]) != expected_grading_key:
        raise T10IntegrityError("Stored Settlement Grade key does not match its payload.")
    linked_rows = connection.execute(
        "SELECT evidence_set_id, ordinal "
        "FROM settlement_grade_evidence WHERE grade_id = ? ORDER BY ordinal, evidence_set_id",
        (grade.grade_id,),
    ).fetchall()
    linked_ids = tuple(str(linked_row[0]) for linked_row in linked_rows)
    ordinals = tuple(int(linked_row[1]) for linked_row in linked_rows)
    if linked_ids != grade.evidence_ids or ordinals != tuple(range(len(linked_ids))):
        raise T10IntegrityError("Stored Settlement Grade evidence links do not match its payload.")
    return grade


def _stored_grade_row(transaction: StoreTransaction | Any, grading_key: str) -> Any:
    return transaction.execute(
        """
        SELECT grade_id, fixture_id, preference_id, matchweek_id, recommendation_id,
               grading_state, settlement_result, reason_code, reason,
               input_evidence_digest, prediction_digest, frozen_evidence_digest,
               correction_sequence, predecessor_grade_id, grade_digest, payload_json,
               grading_key
        FROM settlement_grades
        WHERE grading_key = ?
        ORDER BY correction_sequence DESC, grade_id DESC
        LIMIT 1
        """,
        (grading_key,),
    ).fetchone()


class SettlementGradeRecorder:
    """Persist source records and append-only grades in one bounded transaction."""

    def __init__(self, store: Store, grader: SettlementGrader | None = None) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Settlement grading requires a healthy writable store.")
        self.store = store
        self.grader = grader or SettlementGrader()

    def _insert_evidence(self, transaction: StoreTransaction, evidence: SettlementEvidence) -> None:
        transaction.add_identifier_if_missing(
            CanonicalIdentifier("settlement_evidence", evidence.evidence_id)
        )
        payload = json.dumps(
            evidence.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        transaction.execute(
            """
            INSERT INTO settlement_evidence_sets (
                evidence_set_id, fixture_id, source_level, source_key, record_id,
                record_set_id, evidence_digest, payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_set_id) DO NOTHING
            """,
            (
                evidence.evidence_id,
                evidence.fixture_id,
                cast(SettlementSource, evidence.source_level).value,
                evidence.source_key,
                evidence.record_id,
                evidence.record_set_id,
                evidence.evidence_digest,
                payload,
                evidence.observed_at_utc or evidence.retrieved_at_utc or _utc_now(),
            ),
        )
        row = transaction.execute(
            "SELECT evidence_set_id, fixture_id, source_level, source_key, record_id, "
            "record_set_id, evidence_digest, payload_json "
            "FROM settlement_evidence_sets WHERE evidence_set_id = ?",
            (evidence.evidence_id,),
        ).fetchone()
        if row is None:
            raise T10IntegrityError("Settlement Evidence was not persisted with its identity.")
        stored_evidence = _stored_evidence_from_row(row)
        if stored_evidence != evidence:
            raise T10IntegrityError(
                "Settlement Evidence identity was reused with different content."
            )
        stored_payload = json.loads(str(row[7]))
        if stored_payload != json.loads(payload):
            raise T10IntegrityError(
                "Settlement Evidence identity was reused with different content."
            )

    def _effective_grade(
        self,
        transaction: StoreTransaction,
        grade: SettlementGrade,
    ) -> SettlementGrade | None:
        existing = _stored_grade_row(transaction, grade.grading_key)
        if existing is None:
            return None
        try:
            current = _stored_grade_from_row(
                transaction, existing, expected_grading_key=grade.grading_key
            )
        except (TypeError, ValueError, json.JSONDecodeError, T10Error) as error:
            raise T10IntegrityError("Stored Settlement Grade payload is invalid.") from error
        for label, incoming, stored in (
            ("prediction", grade.prediction_digest, current.prediction_digest),
            ("frozen evidence", grade.frozen_evidence_digest, current.frozen_evidence_digest),
        ):
            if incoming is not None and incoming != stored:
                raise T10IntegrityError(f"Frozen {label} cannot be changed by a correction.")
        incoming_ranks = tuple(item.source_rank for item in grade.evidence)
        if current.reason_code == "SOURCE_CONFLICT" and incoming_ranks:
            conflict_ids_raw = current.provenance.get("conflict_evidence_ids", ())
            conflict_ids = (
                set(conflict_ids_raw)
                if isinstance(conflict_ids_raw, (tuple, list, set, frozenset))
                else set()
            )
            conflict_ranks = tuple(
                item.source_rank
                for item in current.evidence
                if not conflict_ids or item.evidence_id in conflict_ids
            )
            if conflict_ranks and min(conflict_ranks) < min(incoming_ranks):
                return current
        if (
            current.selected_source_level is not None
            and grade.selected_source_level is None
            and grade.reason_code != "WITHDRAWN_RECOMMENDATION"
            and (
                not incoming_ranks
                or min(incoming_ranks) > SOURCE_AUTHORITY_RANK[current.selected_source_level]
            )
        ):
            return current
        if (
            current.evidence_digest == grade.evidence_digest
            and current.grading_state is grade.grading_state
            and current.settlement_result is grade.settlement_result
            and current.reason_code == grade.reason_code
        ):
            return current
        if (
            current.selected_source_level is not None
            and grade.selected_source_level is not None
            and SOURCE_AUTHORITY_RANK[grade.selected_source_level]
            > SOURCE_AUTHORITY_RANK[current.selected_source_level]
        ):
            return current
        return replace(
            grade,
            matchweek_id=current.matchweek_id or grade.matchweek_id,
            recommendation_id=current.recommendation_id or grade.recommendation_id,
            prediction_digest=current.prediction_digest or grade.prediction_digest,
            frozen_evidence_digest=current.frozen_evidence_digest or grade.frozen_evidence_digest,
            correction_sequence=int(existing[12]) + 1,
            predecessor_grade_id=current.grade_id,
            grade_id="",
            grade_digest="",
        )

    def _insert_grade(self, transaction: StoreTransaction, grade: SettlementGrade) -> None:
        if grade.selected_evidence_set_id is not None and grade.selected_evidence_set_id not in {
            item.evidence_id for item in grade.evidence
        }:
            raise T10IntegrityError("Selected Settlement Evidence is not part of the grade input.")
        transaction.add_identifier_if_missing(
            CanonicalIdentifier("settlement_grade", grade.grade_id)
        )
        payload = json.dumps(
            grade.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        transaction.execute(
            """
            INSERT INTO settlement_grades (
                grade_id, grading_key, fixture_id, matchweek_id, recommendation_id,
                preference_id, catalog_version, catalog_digest, grading_state,
                settlement_result, reason_code, reason, selected_evidence_set_id,
                selected_source_level, selected_source_key, input_evidence_digest,
                prediction_digest, frozen_evidence_digest, predecessor_grade_id,
                correction_sequence, grade_digest, payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                grade.grade_id,
                grade.grading_key,
                grade.fixture_id,
                grade.matchweek_id,
                grade.recommendation_id,
                grade.preference.preference_id,
                PREFERENCE_CATALOG_VERSION,
                PREFERENCE_CATALOG_DIGEST,
                grade.grading_state.value,
                grade.settlement_result.value if grade.settlement_result is not None else None,
                grade.reason_code,
                grade.reason,
                grade.selected_evidence_set_id,
                grade.selected_source_level.value
                if grade.selected_source_level is not None
                else None,
                grade.selected_source_key,
                grade.evidence_digest,
                grade.prediction_digest,
                grade.frozen_evidence_digest,
                grade.predecessor_grade_id,
                grade.correction_sequence,
                grade.grade_digest,
                payload,
                _utc_now(),
            ),
        )
        for ordinal, evidence_id in enumerate(grade.evidence_ids):
            transaction.execute(
                """
                INSERT INTO settlement_grade_evidence (grade_id, evidence_set_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (grade.grade_id, evidence_id, ordinal),
            )

    def record(self, grade: SettlementGrade) -> SettlementGrade:
        return self.record_many((grade,))[0]

    def record_many(
        self,
        grades: Iterable[SettlementGrade],
        *,
        failure_hook: Callable[[int], None] | None = None,
    ) -> tuple[SettlementGrade, ...]:
        selected = tuple(grades)
        if not selected:
            return ()
        recorded: list[SettlementGrade] = []
        with self.store.transaction() as transaction:
            for index, grade in enumerate(selected, start=1):
                for evidence in grade.evidence:
                    self._insert_evidence(transaction, evidence)
                existing = _stored_grade_row(transaction, grade.grading_key)
                effective = self._effective_grade(transaction, grade)
                if existing is None:
                    if grade.correction_sequence != 0 or grade.predecessor_grade_id is not None:
                        raise T10IntegrityError(
                            "A first Settlement Grade cannot have correction metadata."
                        )
                    self._insert_grade(transaction, grade)
                    effective = grade
                elif effective is not None and effective.grade_id != str(existing[0]):
                    self._insert_grade(transaction, effective)
                assert effective is not None
                recorded.append(effective)
                if failure_hook is not None:
                    failure_hook(index)
        return tuple(recorded)

    def grade_and_record(
        self,
        preference: BettingPreference | str,
        evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
        *,
        fixture_id: str | None = None,
        finalize: bool = False,
        close_unresolved: bool | None = None,
        withdrawn: bool = False,
        matchweek_id: str = "",
        recommendation_id: str = "",
        prediction_digest: str | None = None,
        frozen_evidence_digest: str | None = None,
        frozen_recommendation: FrozenRecommendation | None = None,
    ) -> SettlementGrade:
        grade = self.grader.grade(
            preference,
            evidence,
            fixture_id=fixture_id,
            finalize=finalize,
            close_unresolved=close_unresolved,
            withdrawn=withdrawn,
            matchweek_id=matchweek_id,
            recommendation_id=recommendation_id,
            prediction_digest=prediction_digest,
            frozen_evidence_digest=frozen_evidence_digest,
            frozen_recommendation=frozen_recommendation,
        )
        return self.record(grade)

    def grade_fixture_and_record(
        self,
        evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
        *,
        fixture_id: str | None = None,
        finalize: bool = False,
        close_unresolved: bool | None = None,
        withdrawn: bool = False,
        matchweek_id: str = "",
        recommendation_ids: Mapping[str, str] | None = None,
        prediction_digests: Mapping[str, str] | None = None,
        frozen_evidence_digest: str | None = None,
    ) -> tuple[SettlementGrade, ...]:
        grades = self.grader.grade_all(
            evidence,
            fixture_id=fixture_id,
            finalize=finalize,
            close_unresolved=close_unresolved,
            withdrawn=withdrawn,
            matchweek_id=matchweek_id,
            recommendation_ids=recommendation_ids,
            prediction_digests=prediction_digests,
            frozen_evidence_digest=frozen_evidence_digest,
        )
        return self.record_many(grades)

    def grades(
        self,
        *,
        fixture_id: str | None = None,
        include_superseded: bool = True,
    ) -> tuple[SettlementGrade, ...]:
        connection = self.store._connection_for_repository()
        where = "" if fixture_id is None else "WHERE fixture_id = ?"
        parameters: tuple[object, ...] = () if fixture_id is None else (fixture_id,)
        rows = connection.execute(
            f"""
            SELECT grade_id, fixture_id, preference_id, matchweek_id, recommendation_id,
                   grading_state, settlement_result, reason_code, reason,
                   input_evidence_digest, prediction_digest, frozen_evidence_digest,
                   correction_sequence, predecessor_grade_id, grade_digest, payload_json,
                   grading_key
            FROM settlement_grades
            {where}
            ORDER BY fixture_id, preference_id, correction_sequence, grade_id
            """,
            parameters,
        ).fetchall()
        selected = tuple(_stored_grade_from_row(connection, row) for row in rows)
        if include_superseded:
            return selected
        current: dict[str, SettlementGrade] = {}
        for grade in selected:
            current[grade.grading_key] = grade
        return tuple(sorted(current.values(), key=lambda item: item.preference.preference_id))

    def current_grade(
        self,
        fixture_id: str,
        preference_id: str,
        *,
        matchweek_id: str = "",
        recommendation_id: str = "",
    ) -> SettlementGrade | None:
        key = f"{fixture_id}|{matchweek_id}|{recommendation_id}|{preference_id}"
        row = _stored_grade_row(self.store._connection_for_repository(), key)
        if row is None:
            return None
        return _stored_grade_from_row(
            self.store._connection_for_repository(), row, expected_grading_key=key
        )

    def evidence_sets(self, fixture_id: str | None = None) -> tuple[SettlementEvidence, ...]:
        connection = self.store._connection_for_repository()
        where = "" if fixture_id is None else "WHERE fixture_id = ?"
        parameters: tuple[object, ...] = () if fixture_id is None else (fixture_id,)
        rows = connection.execute(
            f"""
            SELECT evidence_set_id, fixture_id, source_level, source_key, record_id,
                   record_set_id, evidence_digest, payload_json
            FROM settlement_evidence_sets {where} ORDER BY evidence_set_id
            """,
            parameters,
        ).fetchall()
        return tuple(_stored_evidence_from_row(row) for row in rows)


class T10GradingService:
    """Grade and persist one Fixture's complete v1 matrix."""

    def __init__(self, store: Store, grader: SettlementGrader | None = None) -> None:
        self.recorder = SettlementGradeRecorder(store, grader)

    def grade_fixture(
        self,
        evidence: Iterable[SettlementEvidence | HistoricalMatch | Mapping[str, object]],
        *,
        fixture_id: str | None = None,
        finalize: bool = False,
        close_unresolved: bool | None = None,
        withdrawn: bool = False,
        matchweek_id: str = "",
        recommendation_ids: Mapping[str, str] | None = None,
        prediction_digests: Mapping[str, str] | None = None,
        frozen_evidence_digest: str | None = None,
    ) -> tuple[SettlementGrade, ...]:
        return self.recorder.grade_fixture_and_record(
            evidence,
            fixture_id=fixture_id,
            finalize=finalize,
            close_unresolved=close_unresolved,
            withdrawn=withdrawn,
            matchweek_id=matchweek_id,
            recommendation_ids=recommendation_ids,
            prediction_digests=prediction_digests,
            frozen_evidence_digest=frozen_evidence_digest,
        )


T10Runner = T10GradingService
SettlementStore = SettlementGradeRecorder


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


__all__ = [
    "CATALOG_DIGEST",
    "CATALOG_NAME",
    "CATALOG_VERSION",
    "CORNER_FACTS",
    "DEFAULT_CATALOG",
    "DEFAULT_PREFERENCE_CATALOG",
    "FULL_GOAL_FACTS",
    "HALF_GOAL_FACTS",
    "INITIAL_PREFERENCE_SET",
    "PREFERENCE_CATALOG_DIGEST",
    "PREFERENCE_CATALOG_NAME",
    "PREFERENCE_CATALOG_V1",
    "PREFERENCE_CATALOG_VERSION",
    "PREFERENCE_IDS_V1",
    "SETTLEMENT_RULES_NAME",
    "SETTLEMENT_RULES_VERSION",
    "SOURCE_AUTHORITY_RANK",
    "SOURCE_HIERARCHY",
    "SOURCE_HIERARCHY_NAME",
    "SOURCE_HIERARCHY_VERSION",
    "BettingPreference",
    "FrozenRecommendation",
    "GradingState",
    "MatchPhase",
    "PreferenceCatalog",
    "PreferenceFamily",
    "SettlementEvidence",
    "SettlementGrade",
    "SettlementGradeRecorder",
    "SettlementGrader",
    "SettlementResult",
    "SettlementSource",
    "T10Error",
    "T10Grader",
    "T10GradingService",
    "T10IntegrityError",
    "T10Runner",
    "T10SettlementGrader",
    "T10ValidationError",
    "grade_all_preferences",
    "grade_preference",
]

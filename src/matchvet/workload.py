"""T08 workload evidence from canonical Fixture Revision history.

This module is deliberately schedule-only.  It does not estimate performance,
produce a prediction, grade a match, or make a recommendation.  It accepts
canonical fixture views selected at one Research Cutoff and derives rest,
turnaround, recent schedule density, and cross-competition workload once per
canonical fixture.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from matchvet.evidence import CutoffEligibility, EvidenceClass, EvidenceState
from matchvet.ingestion import deterministic_identifier
from matchvet.store import CanonicalIdentifier, Store


class WorkloadError(Exception):
    """Base class for T08 workload failures."""


class WorkloadValidationError(WorkloadError):
    """A canonical schedule input is malformed."""


class CompetitionType(StrEnum):
    TARGET_LEAGUE = "TARGET_LEAGUE"
    DOMESTIC_CUP = "DOMESTIC_CUP"
    CONTINENTAL = "CONTINENTAL"
    INTERNATIONAL = "INTERNATIONAL"
    FRIENDLY = "FRIENDLY"
    LOWER_DIVISION = "LOWER_DIVISION"
    OTHER = "OTHER"


class FixtureStatus(StrEnum):
    COMPLETED = "COMPLETED"
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class WorkloadState(StrEnum):
    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"


OBSERVED = EvidenceState.OBSERVED
UNKNOWN = EvidenceState.UNKNOWN


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WorkloadValidationError(
            "Workload timestamps must be ISO-8601 values with an explicit UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise WorkloadValidationError("Workload timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _optional_utc(value: str | None) -> str | None:
    return _canonical_utc(value) if value is not None else None


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _as_enum(value: str | StrEnum, enum_type: type[StrEnum], label: str) -> StrEnum:
    text = value.value if isinstance(value, StrEnum) else value
    if not isinstance(text, str):
        raise WorkloadValidationError(f"{label} must be a string.")
    try:
        return enum_type(text.strip().upper())
    except ValueError as error:
        raise WorkloadValidationError(f"Unsupported {label}: {text!r}.") from error


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else value


@dataclass(frozen=True)
class WorkloadRules:
    """Versioned deterministic rules for derived schedule context."""

    name: str = "t08-workload-v1"
    recent_windows_days: tuple[int, ...] = (7, 14, 28)
    context_lookback_days: int = 42
    congestion_threshold_hours: float = 72.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise WorkloadValidationError("Workload rule name is required.")
        if not self.recent_windows_days or any(day <= 0 for day in self.recent_windows_days):
            raise WorkloadValidationError("Recent schedule windows must be positive.")
        if tuple(sorted(set(self.recent_windows_days))) != self.recent_windows_days:
            raise WorkloadValidationError("Recent schedule windows must be sorted and unique.")
        if self.context_lookback_days < max(self.recent_windows_days):
            raise WorkloadValidationError("Context lookback must cover every recent window.")
        if self.congestion_threshold_hours <= 0:
            raise WorkloadValidationError("Congestion threshold must be positive.")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "context_lookback_days": self.context_lookback_days,
                "congestion_threshold_hours": self.congestion_threshold_hours,
                "name": self.name,
                "recent_windows_days": self.recent_windows_days,
            }
        )


@dataclass(frozen=True)
class FixtureProvenance:
    """Source and cutoff metadata retained for one canonical fixture view."""

    source_key: str
    locator: str
    observed_at_utc: str
    published_at_utc: str | None = None
    source_capture_id: str | None = None
    revision_id: str | None = None
    revision_digest: str | None = None
    cutoff_eligibility: CutoffEligibility | str = CutoffEligibility.CUTOFF_VALID

    def __post_init__(self) -> None:
        if not self.source_key.strip() or not self.locator.strip():
            raise WorkloadValidationError("Fixture provenance requires source and locator.")
        object.__setattr__(self, "observed_at_utc", _canonical_utc(self.observed_at_utc))
        object.__setattr__(self, "published_at_utc", _optional_utc(self.published_at_utc))
        selected = _as_enum(self.cutoff_eligibility, CutoffEligibility, "cutoff eligibility")
        object.__setattr__(self, "cutoff_eligibility", selected)

    @property
    def source(self) -> str:
        """Compatibility alias for callers that use the glossary's source term."""

        return self.source_key

    def to_dict(self) -> dict[str, str | None]:
        return {
            "cutoff_eligibility": _enum_value(self.cutoff_eligibility),
            "locator": self.locator,
            "observed_at_utc": self.observed_at_utc,
            "published_at_utc": self.published_at_utc,
            "revision_digest": self.revision_digest,
            "revision_id": self.revision_id,
            "source_capture_id": self.source_capture_id,
            "source_key": self.source_key,
        }


def _provenance_sort_key(item: FixtureProvenance) -> tuple[str, str, str, bytes]:
    # Distinct revisions can share a source, locator, and observation time.
    # The complete record breaks ties independently of set/hash iteration order.
    return (
        item.observed_at_utc,
        item.source_key,
        item.locator,
        _canonical_json(item.to_dict()),
    )


@dataclass(frozen=True)
class CanonicalFixture:
    """One canonical fixture revision as observed by an approved source."""

    fixture_id: str
    home_team_id: str
    away_team_id: str
    kickoff_utc: str | None
    competition_key: str
    competition_name: str
    competition_type: CompetitionType | str
    season: str
    status: FixtureStatus | str
    revision_id: str | None = None
    revision_digest: str | None = None
    provenance: tuple[FixtureProvenance, ...] = ()
    cutoff_eligibility: CutoffEligibility | str | None = None
    home_team_name: str | None = None
    away_team_name: str | None = None

    def __post_init__(self) -> None:
        required = (
            ("fixture_id", self.fixture_id),
            ("home_team_id", self.home_team_id),
            ("away_team_id", self.away_team_id),
            ("competition_key", self.competition_key),
            ("competition_name", self.competition_name),
            ("season", self.season),
        )
        if any(not value.strip() for _name, value in required):
            raise WorkloadValidationError("Canonical fixtures require stable identity fields.")
        if self.home_team_id == self.away_team_id:
            raise WorkloadValidationError("A canonical fixture requires two different teams.")
        object.__setattr__(self, "kickoff_utc", _optional_utc(self.kickoff_utc))
        object.__setattr__(
            self,
            "competition_type",
            _as_enum(self.competition_type, CompetitionType, "competition type"),
        )
        object.__setattr__(self, "status", _as_enum(self.status, FixtureStatus, "fixture status"))
        provenance = tuple(self.provenance)
        if not all(isinstance(item, FixtureProvenance) for item in provenance):
            raise WorkloadValidationError("Fixture provenance must use FixtureProvenance records.")
        object.__setattr__(self, "provenance", provenance)
        if self.cutoff_eligibility is not None:
            object.__setattr__(
                self,
                "cutoff_eligibility",
                _as_enum(self.cutoff_eligibility, CutoffEligibility, "cutoff eligibility"),
            )

    @property
    def effective_cutoff_eligibility(self) -> CutoffEligibility:
        if self.cutoff_eligibility is not None:
            assert isinstance(self.cutoff_eligibility, CutoffEligibility)
            return self.cutoff_eligibility
        if not self.provenance:
            return CutoffEligibility.INDETERMINATE
        eligibility = {item.cutoff_eligibility for item in self.provenance}
        if CutoffEligibility.CUTOFF_VALID in eligibility:
            return CutoffEligibility.CUTOFF_VALID
        if CutoffEligibility.POST_CUTOFF in eligibility:
            return CutoffEligibility.POST_CUTOFF
        return CutoffEligibility.INDETERMINATE

    @property
    def observed_at_utc(self) -> str | None:
        if not self.provenance:
            return None
        return max(item.observed_at_utc for item in self.provenance)

    @property
    def revision_key(self) -> str:
        if self.revision_id is not None:
            return self.revision_id
        return deterministic_identifier(
            "workload_revision",
            f"{self.fixture_id}:{self.kickoff_utc}:{_enum_value(self.status)}:{self.home_team_id}"
            f":{self.away_team_id}",
        )

    @property
    def team_ids(self) -> tuple[str, str]:
        return self.home_team_id, self.away_team_id

    def to_dict(self) -> dict[str, object]:
        return {
            "away_team_id": self.away_team_id,
            "competition_key": self.competition_key,
            "competition_name": self.competition_name,
            "competition_type": _enum_value(self.competition_type),
            "cutoff_eligibility": self.effective_cutoff_eligibility.value,
            "fixture_id": self.fixture_id,
            "home_team_id": self.home_team_id,
            "home_team_name": self.home_team_name,
            "kickoff_utc": self.kickoff_utc,
            "provenance": [item.to_dict() for item in self.provenance],
            "revision_digest": self.revision_digest,
            "revision_id": self.revision_id,
            "season": self.season,
            "status": _enum_value(self.status),
            "away_team_name": self.away_team_name,
        }


# These aliases keep the interface discoverable for callers that name the input by its use.
FixtureHistoryEntry = CanonicalFixture
ScheduleFixture = CanonicalFixture
WorkloadFixture = CanonicalFixture


@dataclass(frozen=True)
class TurnaroundPeriod:
    team_id: str
    previous_fixture_id: str
    next_fixture_id: str
    previous_kickoff_utc: str
    next_kickoff_utc: str
    turnaround_hours: float
    rest_days: float
    congested: bool
    competition_keys: tuple[str, ...]

    @property
    def fixture_ids(self) -> tuple[str, str]:
        return self.previous_fixture_id, self.next_fixture_id

    @property
    def is_congested(self) -> bool:
        return self.congested

    def to_dict(self) -> dict[str, object]:
        return {
            "competition_keys": self.competition_keys,
            "congested": self.congested,
            "next_fixture_id": self.next_fixture_id,
            "next_kickoff_utc": self.next_kickoff_utc,
            "previous_fixture_id": self.previous_fixture_id,
            "previous_kickoff_utc": self.previous_kickoff_utc,
            "rest_days": self.rest_days,
            "team_id": self.team_id,
            "turnaround_hours": self.turnaround_hours,
        }


@dataclass(frozen=True)
class TeamWorkload:
    team_id: str
    state: WorkloadState
    latest_completed_fixture_id: str | None
    rest_days: float | None
    turnaround_hours: float | None
    recent_fixture_ids: tuple[str, ...]
    unique_fixture_count_before_target: int
    schedule_density: Mapping[int, int]
    turnaround_periods: tuple[TurnaroundPeriod, ...]
    congestion_windows: tuple[TurnaroundPeriod, ...]
    cross_competition_fixture_ids: tuple[str, ...]
    unknown_reasons: tuple[str, ...]
    conflict_fixture_ids: tuple[str, ...]
    source_provenance: tuple[FixtureProvenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "schedule_density", MappingProxyType(dict(self.schedule_density)))

    @property
    def congestion_count(self) -> int:
        return len(self.congestion_windows)

    @property
    def rest_state(self) -> EvidenceState:
        return EvidenceState.OBSERVED if self.rest_days is not None else EvidenceState.UNKNOWN

    def to_dict(self) -> dict[str, object]:
        return {
            "congestion_windows": [item.to_dict() for item in self.congestion_windows],
            "conflict_fixture_ids": self.conflict_fixture_ids,
            "cross_competition_fixture_ids": self.cross_competition_fixture_ids,
            "latest_completed_fixture_id": self.latest_completed_fixture_id,
            "recent_fixture_ids": self.recent_fixture_ids,
            "rest_days": self.rest_days,
            "schedule_density": {str(key): value for key, value in self.schedule_density.items()},
            "source_provenance": [item.to_dict() for item in self.source_provenance],
            "state": self.state.value,
            "team_id": self.team_id,
            "turnaround_hours": self.turnaround_hours,
            "turnaround_periods": [item.to_dict() for item in self.turnaround_periods],
            "unique_fixture_count_before_target": self.unique_fixture_count_before_target,
            "unknown_reasons": self.unknown_reasons,
        }


@dataclass(frozen=True)
class WorkloadEvidence:
    target_fixture_id: str
    target_kickoff_utc: str
    cutoff_utc: str
    home: TeamWorkload
    away: TeamWorkload
    state: WorkloadState
    evidence_class: EvidenceClass = EvidenceClass.IMPORTANT
    cutoff_eligibility: CutoffEligibility = CutoffEligibility.CUTOFF_VALID
    source_provenance: tuple[FixtureProvenance, ...] = ()
    rules_name: str = "t08-workload-v1"
    rules_digest: str = ""
    performance_context_state: EvidenceState = EvidenceState.UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_kickoff_utc", _canonical_utc(self.target_kickoff_utc))
        object.__setattr__(self, "cutoff_utc", _canonical_utc(self.cutoff_utc))
        if self.evidence_class is not EvidenceClass.IMPORTANT:
            raise WorkloadValidationError("T08 workload evidence is Important by default.")
        if not self.rules_digest:
            object.__setattr__(self, "rules_digest", WorkloadRules(name=self.rules_name).digest)

    @property
    def rest_days_home(self) -> float | None:
        return self.home.rest_days

    @property
    def rest_days_away(self) -> float | None:
        return self.away.rest_days

    @property
    def congestion_windows(self) -> tuple[TurnaroundPeriod, ...]:
        return self.home.congestion_windows + self.away.congestion_windows

    @property
    def recent_schedule_density(self) -> Mapping[str, Mapping[int, int]]:
        return MappingProxyType(
            {
                "home": self.home.schedule_density,
                "away": self.away.schedule_density,
            }
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "away": self.away.to_dict(),
            "cutoff_eligibility": self.cutoff_eligibility.value,
            "cutoff_utc": self.cutoff_utc,
            "digest": _digest(
                {
                    "target_fixture_id": self.target_fixture_id,
                    "target_kickoff_utc": self.target_kickoff_utc,
                    "cutoff_utc": self.cutoff_utc,
                    "home": self.home.to_dict(),
                    "away": self.away.to_dict(),
                    "state": self.state.value,
                }
            ),
            "evidence_class": self.evidence_class.value,
            "home": self.home.to_dict(),
            "performance_context_state": self.performance_context_state.value,
            "rules_digest": self.rules_digest,
            "rules_name": self.rules_name,
            "source_provenance": [item.to_dict() for item in self.source_provenance],
            "state": self.state.value,
            "target_fixture_id": self.target_fixture_id,
            "target_kickoff_utc": self.target_kickoff_utc,
        }


@dataclass(frozen=True)
class _CanonicalView:
    fixture: CanonicalFixture
    conflict: bool = False


def _same_revision_signature(fixture: CanonicalFixture) -> tuple[object, ...]:
    return (
        fixture.home_team_id,
        fixture.away_team_id,
        fixture.kickoff_utc,
        fixture.competition_key,
        _enum_value(fixture.competition_type),
        _enum_value(fixture.status),
    )


def _select_canonical_views(
    fixtures: Iterable[CanonicalFixture], cutoff: datetime
) -> tuple[tuple[_CanonicalView, ...], tuple[str, ...]]:
    grouped: dict[str, list[CanonicalFixture]] = defaultdict(list)
    for fixture in fixtures:
        if fixture.effective_cutoff_eligibility is not CutoffEligibility.CUTOFF_VALID:
            continue
        observed = fixture.observed_at_utc
        if observed is not None and _parse_utc(observed) > cutoff:
            continue
        grouped[fixture.fixture_id].append(fixture)
    selected: list[_CanonicalView] = []
    conflicts: list[str] = []
    for fixture_id, entries in sorted(grouped.items()):
        if not entries:
            continue
        revision_groups: dict[str, list[CanonicalFixture]] = defaultdict(list)
        for entry in entries:
            revision_groups[entry.revision_key].append(entry)
        revision_conflict = False
        revision_views: list[CanonicalFixture] = []
        for revision_id, revisions in revision_groups.items():
            signatures = {_same_revision_signature(item) for item in revisions}
            if len(signatures) > 1:
                revision_conflict = True
                conflicts.append(fixture_id)
            # Duplicated source rows for one revision are merged only for provenance.
            chosen = max(
                revisions,
                key=lambda item: (
                    item.observed_at_utc or "",
                    item.revision_digest or "",
                    revision_id,
                ),
            )
            provenance = tuple(
                sorted(
                    {item for revision in revisions for item in revision.provenance},
                    key=_provenance_sort_key,
                )
            )
            revision_views.append(
                CanonicalFixture(
                    fixture_id=chosen.fixture_id,
                    home_team_id=chosen.home_team_id,
                    away_team_id=chosen.away_team_id,
                    home_team_name=chosen.home_team_name,
                    away_team_name=chosen.away_team_name,
                    kickoff_utc=chosen.kickoff_utc,
                    competition_key=chosen.competition_key,
                    competition_name=chosen.competition_name,
                    competition_type=chosen.competition_type,
                    season=chosen.season,
                    status=chosen.status,
                    revision_id=chosen.revision_id,
                    revision_digest=chosen.revision_digest,
                    provenance=provenance,
                    cutoff_eligibility=chosen.cutoff_eligibility,
                )
            )
        chosen_revision = max(
            revision_views,
            key=lambda item: (item.observed_at_utc or "", item.revision_key),
        )
        selected.append(_CanonicalView(chosen_revision, revision_conflict))
    return tuple(selected), tuple(sorted(set(conflicts)))


def _team_events(
    views: Sequence[_CanonicalView], team_id: str, target: CanonicalFixture, rules: WorkloadRules
) -> tuple[CanonicalFixture, ...]:
    target_kickoff = _parse_utc(target.kickoff_utc or "")
    lower = target_kickoff - timedelta(days=rules.context_lookback_days)
    events = [
        view.fixture
        for view in views
        if team_id in view.fixture.team_ids
        and view.fixture.kickoff_utc is not None
        and lower <= _parse_utc(view.fixture.kickoff_utc) <= target_kickoff
        and view.fixture.status in {FixtureStatus.COMPLETED, FixtureStatus.SCHEDULED}
    ]
    if not any(item.fixture_id == target.fixture_id for item in events):
        events.append(target)
    unique: dict[str, CanonicalFixture] = {}
    for fixture in events:
        unique.setdefault(fixture.fixture_id, fixture)
    return tuple(
        sorted(
            unique.values(), key=lambda item: (_parse_utc(item.kickoff_utc or ""), item.fixture_id)
        )
    )


def _team_workload(
    team_id: str,
    target: CanonicalFixture,
    views: Sequence[_CanonicalView],
    conflict_fixture_ids: set[str],
    rules: WorkloadRules,
) -> TeamWorkload:
    target_kickoff = _parse_utc(target.kickoff_utc or "")
    team_views = [view for view in views if team_id in view.fixture.team_ids]
    team_events = _team_events(views, team_id, target, rules)
    before = tuple(item for item in team_events if item.fixture_id != target.fixture_id)
    prior = tuple(item for item in before if _parse_utc(item.kickoff_utc or "") < target_kickoff)
    unknown_reasons: set[str] = set()
    team_conflicts = tuple(
        sorted({view.fixture.fixture_id for view in team_views if view.conflict})
    )
    if team_conflicts:
        unknown_reasons.add("FIXTURE_CONFLICT")
    known_team_fixture_ids = {item.fixture_id for item in team_events}
    for view in team_views:
        fixture = view.fixture
        if fixture.fixture_id not in known_team_fixture_ids and fixture.status not in {
            FixtureStatus.POSTPONED,
            FixtureStatus.CANCELLED,
        }:
            unknown_reasons.add("FIXTURE_KICKOFF_UNKNOWN")
        if fixture.kickoff_utc is None and fixture.status not in {
            FixtureStatus.POSTPONED,
            FixtureStatus.CANCELLED,
        }:
            unknown_reasons.add("FIXTURE_KICKOFF_UNKNOWN")
    if any(item in conflict_fixture_ids for item in known_team_fixture_ids):
        unknown_reasons.add("FIXTURE_CONFLICT")

    completed = tuple(item for item in prior if item.status is FixtureStatus.COMPLETED)
    latest = max(completed, key=lambda item: _parse_utc(item.kickoff_utc or ""), default=None)
    rest_days: float | None = None
    turnaround_hours: float | None = None
    if latest is None:
        unknown_reasons.add("NO_COMPLETED_HISTORY")
    elif not team_conflicts:
        elapsed = target_kickoff - _parse_utc(latest.kickoff_utc or "")
        turnaround_hours = elapsed.total_seconds() / 3600.0
        rest_days = elapsed.total_seconds() / 86_400.0

    density: dict[int, int] = {}
    for window_days in rules.recent_windows_days:
        lower = target_kickoff - timedelta(days=window_days)
        density[window_days] = len(
            {
                item.fixture_id
                for item in prior
                if lower <= _parse_utc(item.kickoff_utc or "") < target_kickoff
            }
        )
    periods: list[TurnaroundPeriod] = []
    for previous, following in pairwise(team_events):
        previous_time = _parse_utc(previous.kickoff_utc or "")
        following_time = _parse_utc(following.kickoff_utc or "")
        hours = (following_time - previous_time).total_seconds() / 3600.0
        periods.append(
            TurnaroundPeriod(
                team_id=team_id,
                previous_fixture_id=previous.fixture_id,
                next_fixture_id=following.fixture_id,
                previous_kickoff_utc=previous.kickoff_utc or "",
                next_kickoff_utc=following.kickoff_utc or "",
                turnaround_hours=hours,
                rest_days=hours / 24.0,
                congested=hours <= rules.congestion_threshold_hours,
                competition_keys=tuple(
                    dict.fromkeys((previous.competition_key, following.competition_key))
                ),
            )
        )
    cross_competition = tuple(
        dict.fromkeys(
            item.fixture_id
            for item in prior
            if item.competition_type
            in {
                CompetitionType.DOMESTIC_CUP,
                CompetitionType.CONTINENTAL,
                CompetitionType.INTERNATIONAL,
            }
        )
    )
    provenance = tuple(
        sorted(
            {provenance for item in team_events for provenance in item.provenance},
            key=_provenance_sort_key,
        )
    )
    state = WorkloadState.OBSERVED if not unknown_reasons else WorkloadState.UNKNOWN
    return TeamWorkload(
        team_id=team_id,
        state=state,
        latest_completed_fixture_id=latest.fixture_id if latest is not None else None,
        rest_days=rest_days if state is WorkloadState.OBSERVED else None,
        turnaround_hours=turnaround_hours if state is WorkloadState.OBSERVED else None,
        recent_fixture_ids=tuple(item.fixture_id for item in prior),
        unique_fixture_count_before_target=len({item.fixture_id for item in prior}),
        schedule_density=density,
        turnaround_periods=tuple(periods),
        congestion_windows=tuple(period for period in periods if period.congested),
        cross_competition_fixture_ids=cross_competition,
        unknown_reasons=tuple(sorted(unknown_reasons)),
        conflict_fixture_ids=team_conflicts,
        source_provenance=provenance,
    )


class WorkloadCalculator:
    """Calculate one Target Match's workload evidence from canonical fixtures."""

    def __init__(
        self,
        fixtures: Iterable[CanonicalFixture],
        *,
        cutoff_utc: str,
        rules: WorkloadRules | None = None,
    ) -> None:
        self.fixtures = tuple(fixtures)
        self.cutoff_utc = _canonical_utc(cutoff_utc)
        self.cutoff = _parse_utc(self.cutoff_utc)
        self.rules = rules or WorkloadRules()

    def calculate(self, target: CanonicalFixture) -> WorkloadEvidence:
        if target.kickoff_utc is None:
            raise WorkloadValidationError("A Target Match requires an observed kickoff.")
        if target.effective_cutoff_eligibility is not CutoffEligibility.CUTOFF_VALID:
            raise WorkloadValidationError("Workload evidence requires a cutoff-valid Target Match.")
        if _parse_utc(target.kickoff_utc) <= self.cutoff:
            raise WorkloadValidationError("Workload Target Matches must occur after the cutoff.")
        views, conflict_ids = _select_canonical_views((*self.fixtures, target), self.cutoff)
        home = _team_workload(target.home_team_id, target, views, set(conflict_ids), self.rules)
        away = _team_workload(target.away_team_id, target, views, set(conflict_ids), self.rules)
        provenance = tuple(
            sorted(
                {item for fixture in (target,) for item in fixture.provenance}
                | set(home.source_provenance)
                | set(away.source_provenance),
                key=_provenance_sort_key,
            )
        )
        state = (
            WorkloadState.OBSERVED
            if home.state is WorkloadState.OBSERVED and away.state is WorkloadState.OBSERVED
            else WorkloadState.UNKNOWN
        )
        return WorkloadEvidence(
            target_fixture_id=target.fixture_id,
            target_kickoff_utc=target.kickoff_utc,
            cutoff_utc=self.cutoff_utc,
            home=home,
            away=away,
            state=state,
            source_provenance=provenance,
            rules_name=self.rules.name,
            rules_digest=self.rules.digest,
        )


def calculate_workload(
    target: CanonicalFixture,
    fixtures: Iterable[CanonicalFixture],
    *,
    cutoff_utc: str,
    rules: WorkloadRules | None = None,
) -> WorkloadEvidence:
    """Functional interface for one deterministic workload calculation."""

    return WorkloadCalculator(fixtures, cutoff_utc=cutoff_utc, rules=rules).calculate(target)


def canonical_fixture_id(
    competition_key: str,
    season: str,
    home_team_id: str,
    away_team_id: str,
) -> str:
    """Return the stable identity used when an approved context source lacks an ID."""

    return deterministic_identifier(
        "workload_fixture", f"{competition_key}:{season}:{home_team_id}:{away_team_id}"
    )


@dataclass(frozen=True)
class WorkloadScheduleRecord:
    event_id: str
    fixture: CanonicalFixture
    event_digest: str
    from_existing: bool = False


@dataclass(frozen=True)
class StoredWorkloadEvidence:
    workload_evidence_id: str
    matchweek_id: str
    cutoff_id: str
    target_fixture_id: str
    evidence_state: WorkloadState
    evidence_digest: str
    payload: Mapping[str, object]


def _provenance_from_json(value: str) -> tuple[FixtureProvenance, ...]:
    try:
        raw: object = json.loads(value)
    except json.JSONDecodeError as error:
        raise WorkloadError("Stored workload provenance is malformed.") from error
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise WorkloadError("Stored workload provenance is malformed.")
    result: list[FixtureProvenance] = []
    for item in raw:
        source_key = item.get("source_key")
        locator = item.get("locator")
        observed = item.get("observed_at_utc")
        if not all(isinstance(part, str) for part in (source_key, locator, observed)):
            raise WorkloadError("Stored workload provenance is malformed.")
        published = item.get("published_at_utc")
        result.append(
            FixtureProvenance(
                source_key=source_key,
                locator=locator,
                observed_at_utc=observed,
                published_at_utc=published if isinstance(published, str) else None,
                source_capture_id=(
                    item.get("source_capture_id")
                    if isinstance(item.get("source_capture_id"), str)
                    else None
                ),
                revision_id=(
                    item.get("revision_id") if isinstance(item.get("revision_id"), str) else None
                ),
                revision_digest=(
                    item.get("revision_digest")
                    if isinstance(item.get("revision_digest"), str)
                    else None
                ),
                cutoff_eligibility=str(item.get("cutoff_eligibility", "INDETERMINATE")),
            )
        )
    return tuple(result)


class WorkloadScheduleRecorder:
    """Persist approved domestic-cup and continental schedule context append-only."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Workload schedule recording requires a healthy writable store.")
        self.store = store

    def record(
        self,
        fixture: CanonicalFixture,
        *,
        created_at_utc: str | None = None,
    ) -> WorkloadScheduleRecord:
        records = self.record_many((fixture,), created_at_utc=created_at_utc)
        return records[0]

    def record_many(
        self,
        fixtures: Iterable[CanonicalFixture],
        *,
        created_at_utc: str | None = None,
        failure_hook: Callable[[int], None] | None = None,
    ) -> tuple[WorkloadScheduleRecord, ...]:
        entries = tuple(fixtures)
        created = (
            _canonical_utc(created_at_utc)
            if created_at_utc is not None
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
        results: list[WorkloadScheduleRecord] = []
        with self.store.transaction() as transaction:
            for index, fixture in enumerate(entries, start=1):
                if failure_hook is not None:
                    failure_hook(index)
                observed = fixture.observed_at_utc
                if observed is None:
                    raise WorkloadValidationError(
                        f"Fixture {fixture.fixture_id} requires source observation provenance."
                    )
                event_id = deterministic_identifier(
                    "workload_schedule_event", f"{fixture.fixture_id}:{fixture.revision_key}"
                )
                event_digest = _digest(fixture.to_dict())
                existing = transaction.execute(
                    "SELECT event_digest FROM workload_schedule_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing[0]) != event_digest:
                        raise WorkloadError(
                            f"Workload schedule event {event_id} was reused with different content."
                        )
                    results.append(WorkloadScheduleRecord(event_id, fixture, event_digest, True))
                    continue
                transaction.add_identifier_if_missing(
                    CanonicalIdentifier("workload_schedule_event", event_id)
                )
                transaction.execute(
                    """
                    INSERT INTO workload_schedule_events (
                        event_id, source_fixture_id, revision_id, revision_digest,
                        competition_key, competition_name, competition_type, season_label,
                        home_team_id, home_team_name, away_team_id, away_team_name,
                        kickoff_state, kickoff_utc, fixture_status, observed_at_utc,
                        cutoff_eligibility, provenance_json, event_digest, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        fixture.fixture_id,
                        fixture.revision_key,
                        fixture.revision_digest,
                        fixture.competition_key,
                        fixture.competition_name,
                        _enum_value(fixture.competition_type),
                        fixture.season,
                        fixture.home_team_id,
                        fixture.home_team_name,
                        fixture.away_team_id,
                        fixture.away_team_name,
                        "OBSERVED" if fixture.kickoff_utc is not None else "UNKNOWN",
                        fixture.kickoff_utc,
                        _enum_value(fixture.status),
                        observed,
                        fixture.effective_cutoff_eligibility.value,
                        _canonical_json([item.to_dict() for item in fixture.provenance]).decode(),
                        event_digest,
                        created,
                    ),
                )
                results.append(WorkloadScheduleRecord(event_id, fixture, event_digest))
        return tuple(results)

    def fixtures(self, *, season: str | None = None) -> tuple[CanonicalFixture, ...]:
        rows = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT source_fixture_id, revision_id, revision_digest, competition_key,
                   competition_name, competition_type, season_label, home_team_id,
                   home_team_name, away_team_id, away_team_name, kickoff_utc,
                   fixture_status, observed_at_utc, cutoff_eligibility, provenance_json
            FROM workload_schedule_events
            WHERE (? IS NULL OR season_label = ?)
            ORDER BY source_fixture_id, observed_at_utc, revision_id
            """,
                (season, season),
            )
            .fetchall()
        )
        result: list[CanonicalFixture] = []
        for row in rows:
            result.append(
                CanonicalFixture(
                    fixture_id=str(row[0]),
                    revision_id=str(row[1]),
                    revision_digest=str(row[2]) if row[2] is not None else None,
                    competition_key=str(row[3]),
                    competition_name=str(row[4]),
                    competition_type=str(row[5]),
                    season=str(row[6]),
                    home_team_id=str(row[7]),
                    home_team_name=str(row[8]) if row[8] is not None else None,
                    away_team_id=str(row[9]),
                    away_team_name=str(row[10]) if row[10] is not None else None,
                    kickoff_utc=str(row[11]) if row[11] is not None else None,
                    status=str(row[12]),
                    provenance=_provenance_from_json(str(row[15])),
                    cutoff_eligibility=str(row[14]),
                )
            )
        return tuple(result)


def _t06_fixture_history(store: Store, *, season: str) -> tuple[CanonicalFixture, ...]:
    connection = store._connection_for_repository()
    rows = connection.execute(
        """
        SELECT f.fixture_id, s.season_label, f.home_team_id, home.canonical_name,
               f.away_team_id, away.canonical_name, l.league_key,
               r.revision_id, r.revision_digest, r.kickoff_utc, r.fixture_status,
               r.observed_at_utc, sc.locator, si.source_key,
               sc.source_published_at_utc, sc.capture_id
        FROM fixtures AS f
        JOIN competition_seasons AS s ON s.season_id = f.season_id
        JOIN target_leagues AS l ON l.league_id = f.league_id
        JOIN teams AS home ON home.team_id = f.home_team_id
        JOIN teams AS away ON away.team_id = f.away_team_id
        JOIN fixture_revisions AS r ON r.fixture_id = f.fixture_id
        JOIN source_captures AS sc ON sc.capture_id = r.source_capture_id
        JOIN source_identities AS si ON si.source_id = sc.source_id
        WHERE s.season_label = ?
        ORDER BY f.fixture_id, r.observed_at_utc, r.revision_id
        """,
        (season,),
    ).fetchall()
    result: list[CanonicalFixture] = []
    for row in rows:
        observed = str(row[11])
        kickoff = str(row[9]) if row[9] is not None else None
        result.append(
            CanonicalFixture(
                fixture_id=str(row[0]),
                home_team_id=str(row[2]),
                away_team_id=str(row[4]),
                home_team_name=str(row[3]),
                away_team_name=str(row[5]),
                kickoff_utc=kickoff,
                competition_key=str(row[6]),
                competition_name=str(row[6]),
                competition_type=CompetitionType.TARGET_LEAGUE,
                season=str(row[1]),
                status=str(row[10]),
                revision_id=str(row[7]),
                revision_digest=str(row[8]),
                provenance=(
                    FixtureProvenance(
                        source_key=str(row[13]),
                        locator=str(row[12]),
                        observed_at_utc=observed,
                        published_at_utc=(str(row[14]) if row[14] is not None else None),
                        source_capture_id=str(row[15]),
                        revision_id=str(row[7]),
                        revision_digest=str(row[8]),
                        cutoff_eligibility=CutoffEligibility.CUTOFF_VALID,
                    ),
                ),
            )
        )
    return tuple(result)


def load_canonical_fixture_history(
    store: Store,
    *,
    season: str = "2026-27",
    context_fixtures: Iterable[CanonicalFixture] = (),
) -> tuple[CanonicalFixture, ...]:
    """Load T06 canonical history plus persisted T08 context schedule events."""

    candidates = (
        _t06_fixture_history(store, season=season)
        + WorkloadScheduleRecorder(store).fixtures(season=season)
        + tuple(context_fixtures)
    )
    merged: list[CanonicalFixture] = []
    for candidate in candidates:
        matching = next(
            (
                index
                for index, prior in enumerate(merged)
                if prior.fixture_id == candidate.fixture_id
                and prior.revision_key == candidate.revision_key
                and _same_revision_signature(prior) == _same_revision_signature(candidate)
            ),
            None,
        )
        if matching is None:
            merged.append(candidate)
            continue
        prior = merged[matching]
        provenance = tuple(
            sorted(
                {*prior.provenance, *candidate.provenance},
                key=_provenance_sort_key,
            )
        )
        merged[matching] = replace(candidate, provenance=provenance)
    return tuple(merged)


class WorkloadEvidenceRecorder:
    """Publish immutable derived workload evidence for a frozen Matchweek."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Workload evidence recording requires a healthy writable store.")
        self.store = store

    def record(
        self,
        matchweek_id: str,
        cutoff_id: str,
        evidence: WorkloadEvidence,
        *,
        created_at_utc: str | None = None,
    ) -> StoredWorkloadEvidence:
        payload = evidence.to_dict()
        payload_json = _canonical_json(payload).decode()
        evidence_digest = _digest(payload)
        evidence_id = deterministic_identifier(
            "workload_evidence", f"{matchweek_id}:{evidence.target_fixture_id}"
        )
        created = (
            _canonical_utc(created_at_utc)
            if created_at_utc
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
        with self.store.transaction() as transaction:
            existing = transaction.execute(
                """
                SELECT evidence_state, evidence_digest, payload_json
                FROM workload_evidence
                WHERE matchweek_id = ? AND target_fixture_id = ?
                """,
                (matchweek_id, evidence.target_fixture_id),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != evidence_digest:
                    raise WorkloadError(
                        "Frozen workload evidence was reused with different content."
                    )
                stored_payload = json.loads(str(existing[2]))
                assert isinstance(stored_payload, dict)
                return StoredWorkloadEvidence(
                    evidence_id,
                    matchweek_id,
                    cutoff_id,
                    evidence.target_fixture_id,
                    WorkloadState(str(existing[0])),
                    str(existing[1]),
                    stored_payload,
                )
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("workload_evidence", evidence_id)
            )
            transaction.execute(
                """
                INSERT INTO workload_evidence (
                    workload_evidence_id, matchweek_id, cutoff_id, target_fixture_id,
                    evidence_state, evidence_class, cutoff_eligibility, payload_json,
                    provenance_json, rules_name, rules_digest, evidence_digest, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    matchweek_id,
                    cutoff_id,
                    evidence.target_fixture_id,
                    evidence.state.value,
                    evidence.evidence_class.value,
                    evidence.cutoff_eligibility.value,
                    payload_json,
                    _canonical_json(
                        [item.to_dict() for item in evidence.source_provenance]
                    ).decode(),
                    evidence.rules_name,
                    evidence.rules_digest,
                    evidence_digest,
                    created,
                ),
            )
        return StoredWorkloadEvidence(
            evidence_id,
            matchweek_id,
            cutoff_id,
            evidence.target_fixture_id,
            evidence.state,
            evidence_digest,
            payload,
        )

    def records(self, matchweek_id: str) -> tuple[StoredWorkloadEvidence, ...]:
        rows = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT workload_evidence_id, matchweek_id, cutoff_id, target_fixture_id,
                   evidence_state, evidence_digest, payload_json
            FROM workload_evidence WHERE matchweek_id = ? ORDER BY target_fixture_id
            """,
                (matchweek_id,),
            )
            .fetchall()
        )
        records: list[StoredWorkloadEvidence] = []
        for row in rows:
            payload = json.loads(str(row[6]))
            if not isinstance(payload, dict):
                raise WorkloadError("Stored workload payload is malformed.")
            records.append(
                StoredWorkloadEvidence(
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    WorkloadState(str(row[4])),
                    str(row[5]),
                    payload,
                )
            )
        return tuple(records)

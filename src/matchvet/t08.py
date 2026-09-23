"""T08 workload and weather evidence orchestration.

T08 consumes the frozen T05 Matchweek and canonical T06 Fixture Revisions.  It
may also accept explicitly sourced domestic-cup and continental schedule
context, but it stops at Important Evidence.  No prediction, grading,
recommendation, or T09 sufficiency decision belongs here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime
from enum import StrEnum

from matchvet.artifacts import ArtifactStore
from matchvet.matchweek import (
    FrozenMembership,
    MatchweekFreeze,
    MatchweekWindow,
    read_frozen_matchweek,
)
from matchvet.runs import (
    MIB,
    SETTLED_RESOURCE_BUDGET,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunPhase,
    RunStatus,
    WorkContext,
    WorkResult,
)
from matchvet.store import MIGRATIONS, Store
from matchvet.weather import (
    VenueLocation,
    WeatherClient,
    WeatherEvidence,
    WeatherEvidenceBuilder,
    WeatherEvidenceRecorder,
    WeatherTarget,
)
from matchvet.workload import (
    CanonicalFixture,
    StoredWorkloadEvidence,
    WorkloadCalculator,
    WorkloadEvidence,
    WorkloadEvidenceRecorder,
    WorkloadRules,
    WorkloadScheduleRecorder,
    _canonical_utc,
    load_canonical_fixture_history,
)


class T08Error(Exception):
    """A deterministic T08 orchestration or integrity failure."""


class T08Phase(StrEnum):
    """Public label for the only T08-owned T04 work phase."""

    WORKLOAD_AND_WEATHER = RunPhase.EVIDENCE_ACQUISITION.value


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class T08Plan:
    """Immutable T08 run identity for one frozen Matchweek."""

    friday: str
    season: str = "2026-27"
    workload_rules: WorkloadRules = dataclass_field(default_factory=WorkloadRules)

    def __post_init__(self) -> None:
        MatchweekWindow.for_friday(self.friday)
        if not self.season.strip():
            raise T08Error("T08 plans require a season label.")

    @property
    def window(self) -> MatchweekWindow:
        return MatchweekWindow.for_friday(self.friday)

    @property
    def run_key(self) -> str:
        return f"t08-workload-weather:{self.season}:{self.window.friday_local.isoformat()}"

    @property
    def plan_digest(self) -> str:
        return _digest(
            {
                "friday": self.window.friday_local.isoformat(),
                "rules_digest": self.workload_rules.digest,
                "rules_name": self.workload_rules.name,
                "season": self.season,
            }
        )


@dataclass(frozen=True)
class T08Evidence:
    """The complete T08 result for a frozen Matchweek."""

    matchweek_id: str
    cutoff_utc: str
    workload: tuple[WorkloadEvidence, ...]
    weather: tuple[WeatherEvidence, ...]
    context_fixture_ids: tuple[str, ...] = ()
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cutoff_utc", _canonical_utc(self.cutoff_utc))
        if not self.digest:
            object.__setattr__(self, "digest", _digest(self.to_dict(include_digest=False)))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "context_fixture_ids": self.context_fixture_ids,
            "cutoff_utc": self.cutoff_utc,
            "matchweek_id": self.matchweek_id,
            "weather": [item.to_dict() for item in self.weather],
            "workload": [item.to_dict() for item in self.workload],
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class T08BuildResult:
    """Result plus durable row identities useful to callers and audits."""

    evidence: T08Evidence
    workload_rows: tuple[StoredWorkloadEvidence, ...]
    weather_rows: tuple[object, ...]


def _location_values(
    locations: Mapping[str, VenueLocation] | Iterable[VenueLocation],
) -> tuple[VenueLocation, ...]:
    values = tuple(locations.values()) if isinstance(locations, Mapping) else tuple(locations)
    if not all(isinstance(item, VenueLocation) for item in values):
        raise T08Error("T08 locations must be VenueLocation records.")
    unique: dict[str, VenueLocation] = {}
    for location in values:
        prior = unique.get(location.venue_id)
        if prior is not None and prior != location:
            raise T08Error(f"Venue location {location.venue_id} was reused with different content.")
        unique[location.venue_id] = location
    return tuple(sorted(unique.values(), key=lambda item: item.venue_id))


def _location_map(
    locations: Mapping[str, VenueLocation] | Iterable[VenueLocation],
) -> dict[str, VenueLocation]:
    if isinstance(locations, Mapping):
        mapped = dict(locations)
        values = _location_values(mapped)
        for location in values:
            mapped.setdefault(location.venue_id, location)
        return mapped
    values = _location_values(locations)
    return {item.venue_id: item for item in values}


def _fixture_digest(fixtures: Iterable[CanonicalFixture]) -> str:
    return _digest(
        [item.to_dict() for item in sorted(fixtures, key=lambda item: item.revision_key)]
    )


def _location_digest(locations: Iterable[VenueLocation]) -> str:
    return _digest([item.to_dict() for item in sorted(locations, key=lambda item: item.venue_id)])


def _cutoff_fixture(fixture: CanonicalFixture, cutoff_utc: str) -> CanonicalFixture:
    """Apply the frozen cutoff to a raw T06/T08 fixture view."""

    cutoff = datetime.fromisoformat(_canonical_utc(cutoff_utc))
    if fixture.observed_at_utc is None:
        return replace(fixture, cutoff_eligibility="INDETERMINATE")
    observed = datetime.fromisoformat(fixture.observed_at_utc)
    published = [
        item.published_at_utc for item in fixture.provenance if item.published_at_utc is not None
    ]
    if observed > cutoff or any(datetime.fromisoformat(item) > cutoff for item in published):
        return replace(fixture, cutoff_eligibility="POST_CUTOFF")
    return replace(fixture, cutoff_eligibility="CUTOFF_VALID")


def _target_fixture(
    membership: FrozenMembership,
    history: Iterable[CanonicalFixture],
    cutoff_utc: str,
) -> CanonicalFixture:
    candidates = [item for item in history if item.fixture_id == membership.subject_id]
    if membership.controlling_revision_id is not None:
        candidates = [
            item
            for item in candidates
            if item.revision_id == membership.controlling_revision_id
            or item.revision_digest == membership.controlling_revision_digest
        ]
    if not candidates:
        raise T08Error(
            "T05 controlling Fixture Revision is unavailable for "
            f"Target Match {membership.subject_id}."
        )
    selected = max(
        candidates,
        key=lambda item: (item.observed_at_utc or "", item.revision_key),
    )
    selected = _cutoff_fixture(selected, cutoff_utc)
    if selected.effective_cutoff_eligibility.value != "CUTOFF_VALID":
        raise T08Error(
            f"Target Match {membership.subject_id} has no cutoff-valid canonical fixture view."
        )
    if selected.kickoff_utc != membership.original_kickoff_utc:
        raise T08Error(
            f"Target Match {membership.subject_id} disagrees with the frozen T05 kickoff."
        )
    if membership.controlling_revision_digest is not None and (
        selected.revision_digest != membership.controlling_revision_digest
    ):
        raise T08Error(
            f"Target Match {membership.subject_id} disagrees with the frozen T05 revision."
        )
    return selected


def _location_for_fixture(
    fixture_id: str,
    locations: Mapping[str, VenueLocation] | Iterable[VenueLocation],
) -> VenueLocation | None:
    if isinstance(locations, Mapping):
        return locations.get(fixture_id)
    return next((item for item in locations if item.venue_id == fixture_id), None)


def build_t08_input_contract(
    store: Store,
    plan: T08Plan,
    *,
    context_fixtures: Iterable[CanonicalFixture] = (),
    locations: Mapping[str, VenueLocation] | Iterable[VenueLocation] = (),
    refresh_weather: bool = False,
) -> RunInputContract:
    """Build the exact T04 identity contract for T08 start/resume."""

    freeze = read_frozen_matchweek(store, plan.friday, season=plan.season)
    context = tuple(context_fixtures)
    history = load_canonical_fixture_history(store, season=plan.season, context_fixtures=context)
    location_values = _location_values(locations)
    schema_identity = ":".join(migration.checksum for migration in MIGRATIONS)
    return RunInputContract.from_values(
        {
            "source": f"T06_T08_FIXTURE_HISTORY:{_fixture_digest(history)}",
            "cutoff": (
                f"T05:{freeze.cutoff.cutoff_utc}:{freeze.membership_manifest_digest}:"
                f"{freeze.revision_snapshot_digest}"
            ),
            "preference_set": "T08:NOT_APPLICABLE",
            "policy": (f"T08:OPEN_METEO_ONLY_CUTOFF_VALID:REFRESH_WEATHER:{int(refresh_weather)}"),
            "model": "OPEN_METEO:best_match:hourly",
            "feature": (
                f"T08:WORKLOAD_WEATHER:{plan.workload_rules.digest}:"
                f"{_location_digest(location_values)}"
            ),
            "research_rule": "T08_WORKLOAD_WEATHER_EVIDENCE_V1",
            "canonical_contract": "MATCHVET_CANONICAL_CONTRACT_V1",
            "schema": schema_identity,
            "environment": "T08:LOCAL_CACHE_AND_T04_CHECKPOINTS",
            "software": "MATCHVET_T08_WORKLOAD_WEATHER_V1",
        },
        artifact_digests=(
            freeze.snapshot_manifest_digest,
            freeze.membership_manifest_digest,
            freeze.revision_snapshot_digest,
        ),
        predecessor_digests=(
            freeze.membership_manifest_digest,
            freeze.revision_snapshot_digest,
            freeze.snapshot_manifest_digest,
        ),
    )


class T08EvidenceBuilder:
    """Build and durably publish T08 evidence for the frozen Target Matches."""

    def __init__(
        self,
        store: Store,
        *,
        weather_client: WeatherClient | None,
        context_fixtures: Iterable[CanonicalFixture] = (),
        locations: Mapping[str, VenueLocation] | Iterable[VenueLocation] = (),
        rules: WorkloadRules | None = None,
        refresh_weather: bool = False,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T08 evidence building requires a healthy writable store.")
        self.store = store
        self.weather_client = weather_client
        self.context_fixtures = tuple(context_fixtures)
        self.locations = _location_map(locations)
        self.rules = rules or WorkloadRules()
        self.refresh_weather = refresh_weather
        self.failure_hook = failure_hook

    def build(self, freeze: MatchweekFreeze) -> T08BuildResult:
        context_rows = WorkloadScheduleRecorder(self.store).record_many(self.context_fixtures)
        for location in _location_values(self.locations):
            # Locations are persisted before a network call so a retry retains
            # the exact coordinates and source provenance used by the request.
            from matchvet.weather import WeatherLocationRecorder

            WeatherLocationRecorder(self.store).record(location)

        raw_history = load_canonical_fixture_history(
            self.store,
            season=freeze.season,
            context_fixtures=self.context_fixtures,
        )
        history = tuple(_cutoff_fixture(item, freeze.cutoff.cutoff_utc) for item in raw_history)
        workload_recorder = WorkloadEvidenceRecorder(self.store)
        weather_recorder = WeatherEvidenceRecorder(self.store)
        weather_builder = WeatherEvidenceBuilder(self.weather_client)
        workload_values: list[WorkloadEvidence] = []
        weather_values: list[WeatherEvidence] = []
        workload_rows: list[StoredWorkloadEvidence] = []
        weather_rows: list[object] = []
        for index, membership in enumerate(
            sorted(freeze.target_matches, key=lambda item: item.subject_id), start=1
        ):
            if self.failure_hook is not None:
                self.failure_hook(index, membership)
            target = _target_fixture(membership, history, freeze.cutoff.cutoff_utc)
            workload = WorkloadCalculator(
                history,
                cutoff_utc=freeze.cutoff.cutoff_utc,
                rules=self.rules,
            ).calculate(target)
            workload_values.append(workload)
            workload_rows.append(
                workload_recorder.record(
                    freeze.cutoff.matchweek_id,
                    freeze.cutoff.cutoff_id,
                    workload,
                )
            )
            weather_batch = weather_builder.build(
                (
                    WeatherTarget(
                        fixture_id=target.fixture_id,
                        target_time_utc=target.kickoff_utc or "",
                        cutoff_utc=freeze.cutoff.cutoff_utc,
                        location=self.locations.get(target.fixture_id),
                        eligible_target_match=True,
                    ),
                ),
                refresh=self.refresh_weather,
            )
            weather = weather_batch.evidence[0]
            weather_values.append(weather)
            weather_rows.append(
                weather_recorder.record(
                    freeze.cutoff.matchweek_id,
                    weather,
                    location=self.locations.get(target.fixture_id),
                )
            )
        result = T08Evidence(
            matchweek_id=freeze.cutoff.matchweek_id,
            cutoff_utc=freeze.cutoff.cutoff_utc,
            workload=tuple(workload_values),
            weather=tuple(weather_values),
            context_fixture_ids=tuple(row.fixture.fixture_id for row in context_rows),
        )
        return T08BuildResult(result, tuple(workload_rows), tuple(weather_rows))


class T08EvidenceRunner:
    """Run T08 through T04 checkpoints, cache reuse, and resumable publication."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T08 run coordination requires a healthy writable store.")
        self.store = store
        self.last_result: T08BuildResult | None = None

    def start(
        self,
        plan: T08Plan,
        *,
        observation: ResourceObservation,
        weather_client: WeatherClient | None,
        context_fixtures: Iterable[CanonicalFixture] = (),
        locations: Mapping[str, VenueLocation] | Iterable[VenueLocation] = (),
        refresh_weather: bool = False,
        progress: Callable[[RunStatus], None] | None = None,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> RunStatus:
        context = tuple(context_fixtures)
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        status = coordinator.start(
            matchweek=plan.run_key,
            inputs=build_t08_input_contract(
                self.store,
                plan,
                context_fixtures=context,
                locations=locations,
                refresh_weather=refresh_weather,
            ),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda work: self._execute(
                plan,
                work,
                weather_client=weather_client,
                context_fixtures=context,
                locations=locations,
                refresh_weather=refresh_weather,
                failure_hook=failure_hook,
            ),
            progress=progress,
        )
        return status

    def resume(
        self,
        run_id: str,
        plan: T08Plan,
        *,
        observation: ResourceObservation,
        weather_client: WeatherClient | None,
        context_fixtures: Iterable[CanonicalFixture] = (),
        locations: Mapping[str, VenueLocation] | Iterable[VenueLocation] = (),
        refresh_weather: bool = False,
        progress: Callable[[RunStatus], None] | None = None,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> RunStatus:
        context = tuple(context_fixtures)
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        return coordinator.resume(
            run_id,
            inputs=build_t08_input_contract(
                self.store,
                plan,
                context_fixtures=context,
                locations=locations,
                refresh_weather=refresh_weather,
            ),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda work: self._execute(
                plan,
                work,
                weather_client=weather_client,
                context_fixtures=context,
                locations=locations,
                refresh_weather=refresh_weather,
                failure_hook=failure_hook,
            ),
            progress=progress,
        )

    def _estimate(self, plan: T08Plan) -> ResourceEstimate:
        freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        target_count = max(1, len(freeze.target_matches))
        return ResourceEstimate(
            storage_growth_bytes=target_count * 128 * 1024,
            peak_memory_bytes=256 * MIB,
            duration_seconds=60 + target_count * 15,
            network_bytes=target_count * 128 * 1024,
            cpu_heavy_operations=1,
        )

    def _execute(
        self,
        plan: T08Plan,
        context: WorkContext,
        *,
        weather_client: WeatherClient | None,
        context_fixtures: tuple[CanonicalFixture, ...],
        locations: Mapping[str, VenueLocation] | Iterable[VenueLocation],
        refresh_weather: bool,
        failure_hook: Callable[[int, FrozenMembership], None] | None,
    ) -> WorkResult:
        if context.phase is not RunPhase.EVIDENCE_ACQUISITION:
            return WorkResult.for_phase(context.phase)
        freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        result = T08EvidenceBuilder(
            self.store,
            weather_client=weather_client,
            context_fixtures=context_fixtures,
            locations=locations,
            rules=plan.workload_rules,
            refresh_weather=refresh_weather,
            failure_hook=failure_hook,
        ).build(freeze)
        self.last_result = result
        content = _canonical_json(result.evidence.to_dict())
        artifact = ArtifactStore(self.store).publish_artifact(
            content,
            "application/vnd.matchvet.t08-workload-weather+json",
            expected_digest=_digest(result.evidence.to_dict()),
            retention_class="PROTECTED",
        )
        return WorkResult(result_digest=result.evidence.digest, artifact_digests=(artifact.digest,))


# Descriptive aliases keep the T08 seam easy to find without creating a second implementation.
WorkloadWeatherEvidenceRunner = T08EvidenceRunner
WorkloadWeatherEvidenceBuilder = T08EvidenceBuilder

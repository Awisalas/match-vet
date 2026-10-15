"""Controlled five-league interval fixture acquisition through supported feeds."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta

from matchvet.fixture_coverage import (
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    ProviderAttempt,
    ProviderAttemptState,
)
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.ingestion import (
    FixtureCaptureObservation,
    FixtureHistoryImporter,
    LeagueConfig,
    OpenFootballJSONParser,
    OpenFootballTextParser,
    SourceCaptureInput,
    SourceFetcher,
    SourceKind,
    SourceParseError,
    SourceUnavailable,
    TeamIdentityPolicy,
    _canonical_f01_utc,
    _fixture_status,
    _source_timezone,
    deterministic_identifier,
    league_by_key,
    openfootball_text_url,
    openfootball_url,
)
from matchvet.provider_health_acquisition import build_slate_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.slate_fixture_coverage import (
    SlateFixtureCoverageAssessment,
    SlateFixtureScope,
    assess_slate_fixture_coverage,
    slate_fixture_scopes,
)
from matchvet.slate_window import SlateWindow


@dataclass(frozen=True, slots=True)
class SlateFixtureAcquisition:
    assessment: SlateFixtureCoverageAssessment
    health_digests: tuple[str, ...]
    diagnostics: tuple[str, ...]


class SlateFixtureCoverageAcquirer:
    """Acquire every configured five-league JSON/text feed for one exact window."""

    def __init__(
        self,
        importer: FixtureHistoryImporter,
        fetcher: SourceFetcher,
        *,
        attempted_at: Callable[[], str],
    ) -> None:
        self._importer = importer
        self._fetcher = fetcher
        self._attempted_at = attempted_at
        self._json_parser = OpenFootballJSONParser()
        self._text_parser = OpenFootballTextParser()

    def acquire(self, window: SlateWindow) -> SlateFixtureAcquisition:
        """Persist exact F01 first, then atomically persist one F05 record per attempt."""
        attempts: list[ProviderAttempt] = []
        diagnostics: dict[str, str] = {}
        capture_scopes: dict[str, str] = {}
        capture_rows: dict[str, set[str]] = {}
        for scope in _slate_scopes(window):
            league = league_by_key(scope.league_key)
            feeds = (
                (
                    "openfootball-json",
                    openfootball_url(league, scope.season),
                    SourceKind.OPENFOOTBALL,
                    self._json_parser,
                ),
                (
                    "openfootball-footballtxt",
                    openfootball_text_url(league, scope.season),
                    SourceKind.OPENFOOTBALL_TEXT,
                    self._text_parser,
                ),
            )
            for provider_id, url, source_kind, parser in feeds:
                attempt, row_keys, diagnostic = self._acquire_feed(
                    scope_id=scope.scope_id,
                    league=league,
                    season=scope.season,
                    provider_id=provider_id,
                    url=url,
                    source_kind=source_kind,
                    parser=parser,
                )
                attempts.append(attempt)
                if attempt.capture_id is not None:
                    capture_scopes[attempt.capture_id] = scope.scope_id
                    capture_rows[attempt.capture_id] = set(row_keys)
                if diagnostic is not None:
                    diagnostics[attempt.attempt_id] = diagnostic

        revisions, identities = _retained_candidates(
            self._importer,
            window,
            capture_scopes,
            capture_rows,
        )
        assessment = assess_slate_fixture_coverage(
            window=window,
            provider_attempts=tuple(attempts),
            coverage_evidence=(),
            fixture_revisions=revisions,
            identity_resolutions=identities,
            freshness_results=(),
        )
        FixtureCoverageRepository(self._importer._store).persist_slate(assessment)
        records = build_slate_provider_health_records(assessment, attempt_diagnostics=diagnostics)
        health_digests = ProviderHealthRepository(self._importer._store).persist_many(records)
        return SlateFixtureAcquisition(
            assessment, health_digests, tuple(sorted(diagnostics.values()))
        )

    def _acquire_feed(
        self,
        *,
        scope_id: str,
        league: LeagueConfig,
        season: str,
        provider_id: str,
        url: str,
        source_kind: SourceKind,
        parser: OpenFootballJSONParser | OpenFootballTextParser,
    ) -> tuple[ProviderAttempt, tuple[str, ...], str | None]:
        try:
            downloaded = self._fetcher.fetch(url, cache_key=f"{provider_id}:{league.key}:{season}")
        except SourceUnavailable as error:
            if error.terminal:
                raise
            return (
                _attempt(
                    scope_id,
                    provider_id,
                    ProviderAttemptState.UNAVAILABLE,
                    _canonical_f01_utc(self._attempted_at()),
                    error.http_status,
                    None,
                    None,
                ),
                (),
                str(error),
            )
        capture = SourceCaptureInput(
            source_url=url,
            retrieved_at_utc=downloaded.retrieved_at_utc,
            response_status=downloaded.response_status,
            content_type=downloaded.content_type,
            observed_terms="OpenFootball CC0",
            cache_key=f"{provider_id}:{league.key}:{season}",
            transport_provenance=downloaded.transport_provenance,
        )
        try:
            dataset = parser.parse(downloaded.content, league=league, season=season)
        except SourceParseError as error:
            retained = self._importer.retain_capture(
                source_kind=source_kind,
                league=league,
                season=season,
                content=downloaded.content,
                capture=capture,
            )
            return (
                _attempt(
                    scope_id,
                    provider_id,
                    ProviderAttemptState.MALFORMED,
                    _canonical_f01_utc(downloaded.retrieved_at_utc),
                    downloaded.response_status,
                    retained.capture_id,
                    retained.content_sha256,
                ),
                (),
                str(error),
            )
        scheduled_dataset = replace(
            dataset,
            rows=tuple(row for row in dataset.rows if _fixture_status(row) != "COMPLETED"),
        )
        imported = self._importer.import_dataset(
            scheduled_dataset,
            downloaded.content,
            capture,
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        return (
            _attempt(
                scope_id,
                provider_id,
                ProviderAttemptState.CAPTURED,
                _canonical_f01_utc(downloaded.retrieved_at_utc),
                downloaded.response_status,
                imported.source_capture_id,
                imported.source_digest,
            ),
            tuple(row.source_row_key for row in scheduled_dataset.rows),
            None,
        )


def _slate_scopes(window: SlateWindow) -> tuple[SlateFixtureScope, ...]:
    return slate_fixture_scopes(window)


def _attempt(
    scope_id: str,
    provider_id: str,
    state: ProviderAttemptState,
    checked_at: str,
    status: int | None,
    capture_id: str | None,
    capture_digest: str | None,
) -> ProviderAttempt:
    identity = ":".join(
        (
            scope_id,
            provider_id,
            state.value,
            checked_at,
            str(status or ""),
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
        retrieved_at_utc=checked_at,
        http_status=status,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )


def _retained_candidates(
    importer: FixtureHistoryImporter,
    window: SlateWindow,
    capture_scopes: dict[str, str],
    capture_rows: dict[str, set[str]],
) -> tuple[tuple[FixtureRevisionReference, ...], tuple[FixtureIdentityResolution, ...]]:
    revisions_by_id: dict[str, FixtureRevisionReference] = {}
    revisions_by_fixture: dict[tuple[str, str], set[str]] = defaultdict(set)
    assertions_by_fixture: dict[tuple[str, str], set[str]] = defaultdict(set)
    captures_by_fixture: dict[tuple[str, str], set[str]] = defaultdict(set)
    unresolved: dict[str, FixtureIdentityResolution] = {}
    start = datetime.fromisoformat(window.start_utc)
    end = datetime.fromisoformat(window.end_utc)
    for capture_id, scope_id in capture_scopes.items():
        league = league_by_key(scope_id.split(":", 1)[0])
        for observation in importer.observations_for_capture(capture_id):
            if observation.source_row_key not in capture_rows[capture_id]:
                continue
            if not _observation_in_window(observation, start, end, league.timezone):
                continue
            if observation.fixture_id is None:
                candidate_id = deterministic_identifier(
                    "fixture_candidate", f"{capture_id}:{observation.source_row_key}"
                )
                unresolved[candidate_id] = FixtureIdentityResolution(
                    candidate_id=candidate_id,
                    scope_id=scope_id,
                    state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
                    reason_code=observation.reason_code or "TEAM_MAPPING_UNRESOLVED",
                    source_capture_ids=(capture_id,),
                    source_assertion_ids=observation.source_assertion_ids,
                )
                continue
            if observation.revision_id is None or observation.revision_digest is None:
                raise ValueError("Retained slate fixture observation lacks its exact revision.")
            current = revisions_by_id.get(observation.revision_id)
            revisions_by_id[observation.revision_id] = FixtureRevisionReference(
                scope_id=scope_id,
                fixture_id=observation.fixture_id,
                revision_id=observation.revision_id,
                revision_digest=observation.revision_digest,
                source_capture_ids=tuple(
                    sorted(set(current.source_capture_ids if current else ()) | {capture_id})
                ),
                source_assertion_ids=tuple(
                    sorted(
                        set(current.source_assertion_ids if current else ())
                        | set(observation.source_assertion_ids)
                    )
                ),
            )
            key = scope_id, observation.fixture_id
            revisions_by_fixture[key].add(observation.revision_id)
            assertions_by_fixture[key].update(observation.source_assertion_ids)
            captures_by_fixture[key].add(capture_id)
    resolved = tuple(
        FixtureIdentityResolution(
            candidate_id=deterministic_identifier("fixture_candidate", f"{scope_id}:{fixture_id}"),
            scope_id=scope_id,
            state=FixtureIdentityState.RESOLVED,
            canonical_fixture_id=fixture_id,
            revision_ids=tuple(sorted(revision_ids)),
            source_capture_ids=tuple(sorted(captures_by_fixture[(scope_id, fixture_id)])),
            source_assertion_ids=tuple(sorted(assertions_by_fixture[(scope_id, fixture_id)])),
        )
        for (scope_id, fixture_id), revision_ids in sorted(revisions_by_fixture.items())
    )
    return tuple(revisions_by_id.values()), (*resolved, *unresolved.values())


def _observation_in_window(
    observation: FixtureCaptureObservation,
    start: datetime,
    end: datetime,
    zone_name: str,
) -> bool:
    if observation.kickoff_utc is not None:
        kickoff = datetime.fromisoformat(observation.kickoff_utc.replace("Z", "+00:00"))
        return start <= kickoff < end
    if observation.kickoff_local_date is None:
        return False
    local_date: date = observation.kickoff_local_date
    zone = _source_timezone(zone_name, local_date)
    day_start = datetime.combine(local_date, time.min, zone).astimezone(UTC)
    next_date = local_date + timedelta(days=1)
    day_end = datetime.combine(
        next_date, time.min, _source_timezone(zone_name, next_date)
    ).astimezone(UTC)
    return day_start >= start and day_end <= end

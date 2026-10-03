"""Research-only operator citations for unsupported scheduled fixture scopes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.fixture_coverage import fixture_scopes_for_matchweek
from matchvet.ingestion import (
    FixtureHistoryImporter,
    ImportResult,
    LeagueConfig,
    MappingState,
    ParsedDataset,
    ParsedRow,
    SourceCaptureInput,
    SourceKind,
    TeamIdentityPolicy,
    TeamResolution,
    _source_timezone,
    deterministic_identifier,
    league_by_key,
    sha256_bytes,
)
from matchvet.store import Store

OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION = "operator-official-fixture-observation-v1"
OPERATOR_FIXTURE_OBSERVATION_SCHEMA_VERSION = 1
OPERATOR_FIXTURE_OBSERVATION_POLICY_ID = "matchvet:operator-official-fixture-observation"
OPERATOR_FIXTURE_OBSERVATION_POLICY_VERSION = "1"
OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE = (
    "application/vnd.matchvet.operator-official-fixture-observation+json"
)
OPERATOR_FIXTURE_OBSERVATION_SOURCE_KEY = "pro-league-official-manual-citation"

_MAX_TEXT = 256
_MAX_OPERATOR_ID = 120
_TEAM_FIXTURES_PATH = re.compile(
    r"^/(?P<language>fr|nl|en)/equipes/(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)/fixtures-results$"
)
_STATUS_VALUES = frozenset({"SCHEDULED", "POSTPONED", "CANCELLED"})
_SUPPORTED_LEAGUE = "belgian_pro_league"
_SUPPORTED_SEASON = "2026-27"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _require_text(value: str, label: str, *, maximum: int = _MAX_TEXT) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be nonempty and at most {maximum} characters.")
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} must not contain surrounding whitespace or control text.")


def _date_text(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must use YYYY-MM-DD form.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD form.") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use canonical YYYY-MM-DD form.")
    return value


def _canonical_utc(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 instant with a UTC offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 instant with a UTC offset.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset.")
    canonical = parsed.astimezone(UTC).isoformat()
    if canonical != value:
        raise ValueError(f"{label} must be canonical UTC.")
    return value


@dataclass(frozen=True)
class OperatorFixtureObservationPublicationRule:
    publication_id: str
    publication_type: str
    official_url: str


@dataclass(frozen=True)
class OperatorFixtureObservationPolicy:
    policy_id: str
    policy_version: str
    league_key: str
    season: str
    publisher_id: str
    publisher_name: str
    competition_id: str
    competition_name: str
    allowed_host: str
    publication_rules: tuple[OperatorFixtureObservationPublicationRule, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        if (
            self.policy_id != OPERATOR_FIXTURE_OBSERVATION_POLICY_ID
            or self.policy_version != OPERATOR_FIXTURE_OBSERVATION_POLICY_VERSION
            or self.league_key != _SUPPORTED_LEAGUE
            or self.season != _SUPPORTED_SEASON
            or self.publisher_id != "pro-league"
            or self.publisher_name != "Pro League"
            or self.competition_id != "jupiler-pro-league"
            or self.competition_name != "Jupiler Pro League"
            or self.allowed_host != "www.proleague.be"
        ):
            raise ValueError("Unsupported official fixture observation policy identity.")
        expected_rules = (
            OperatorFixtureObservationPublicationRule(
                publication_id="jpl-kalender",
                publication_type="OFFICIAL_COMPETITION_CALENDAR",
                official_url="https://www.proleague.be/jpl-kalender!",
            ),
            OperatorFixtureObservationPublicationRule(
                publication_id="team-fixtures:{team-slug}",
                publication_type="OFFICIAL_TEAM_FIXTURES",
                official_url=("https://www.proleague.be/fr/equipes/{team-slug}/fixtures-results"),
            ),
        )
        if self.publication_rules != expected_rules:
            raise ValueError("Official fixture observation publication rules are unsupported.")
        expected_digest = _policy_digest(self)
        if self.digest and self.digest != expected_digest:
            raise ValueError("Official fixture observation policy digest does not match.")
        object.__setattr__(self, "digest", expected_digest)

    def validate_publication(
        self,
        *,
        publication_id: str,
        publication_type: str,
        official_url: str,
    ) -> None:
        _require_text(publication_id, "Publication ID")
        _require_text(publication_type, "Publication type")
        _require_text(official_url, "Official URL", maximum=2048)
        parsed = urlsplit(official_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.allowed_host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Official URL must use an approved Pro League HTTPS address.")
        if (
            publication_id == "jpl-kalender"
            and publication_type == "OFFICIAL_COMPETITION_CALENDAR"
            and parsed.path == "/jpl-kalender!"
        ):
            return
        match = _TEAM_FIXTURES_PATH.fullmatch(parsed.path)
        if (
            match is not None
            and publication_type == "OFFICIAL_TEAM_FIXTURES"
            and publication_id == f"team-fixtures:{match.group('slug')}"
        ):
            return
        raise ValueError("Publication ID, type, and URL are not approved by this policy.")


def operator_fixture_observation_policy_v1() -> OperatorFixtureObservationPolicy:
    return OperatorFixtureObservationPolicy(
        policy_id=OPERATOR_FIXTURE_OBSERVATION_POLICY_ID,
        policy_version=OPERATOR_FIXTURE_OBSERVATION_POLICY_VERSION,
        league_key=_SUPPORTED_LEAGUE,
        season=_SUPPORTED_SEASON,
        publisher_id="pro-league",
        publisher_name="Pro League",
        competition_id="jupiler-pro-league",
        competition_name="Jupiler Pro League",
        allowed_host="www.proleague.be",
        publication_rules=(
            OperatorFixtureObservationPublicationRule(
                publication_id="jpl-kalender",
                publication_type="OFFICIAL_COMPETITION_CALENDAR",
                official_url="https://www.proleague.be/jpl-kalender!",
            ),
            OperatorFixtureObservationPublicationRule(
                publication_id="team-fixtures:{team-slug}",
                publication_type="OFFICIAL_TEAM_FIXTURES",
                official_url=("https://www.proleague.be/fr/equipes/{team-slug}/fixtures-results"),
            ),
        ),
    )


def _policy_digest(policy: OperatorFixtureObservationPolicy) -> str:
    payload = {key: value for key, value in asdict(policy).items() if key != "digest"}
    return f"sha256:{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


@dataclass(frozen=True)
class OperatorOfficialFixtureObservation:
    contract_version: str
    schema_version: int
    league_key: str
    season: str
    matchweek_friday: str
    scope_id: str
    home_source_name: str
    away_source_name: str
    home_team_id: str
    away_team_id: str
    kickoff_precision: str
    kickoff_utc: str | None
    source_local_date: str
    fixture_status: str
    publisher_id: str
    publisher_name: str
    competition_id: str
    competition_name: str
    publication_id: str
    publication_type: str
    official_url: str
    title_or_publication_id: str
    publication_date: str | None
    operator_id: str
    observed_at_utc: str
    policy_id: str
    policy_version: str
    policy_digest: str
    mode: str
    access_method: str
    source_class: str
    digest: str = ""

    def __post_init__(self) -> None:
        if (
            self.contract_version != OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != OPERATOR_FIXTURE_OBSERVATION_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported Operator Official Fixture Observation version.")
        for name, value in (
            ("League key", self.league_key),
            ("Season", self.season),
            ("Matchweek Friday", self.matchweek_friday),
        ):
            _require_text(value, name)
        _date_text(self.matchweek_friday, "Matchweek Friday")
        if self.league_key != _SUPPORTED_LEAGUE or self.season != _SUPPORTED_SEASON:
            raise ValueError("Observation must use the policy-supported Belgian season.")
        try:
            scopes = fixture_scopes_for_matchweek(self.matchweek_friday, season=self.season)
        except ValueError as error:
            raise ValueError(
                "Matchweek scope must use an exact Friday in the supported season."
            ) from error
        expected_scope = next(item for item in scopes if item.league_key == _SUPPORTED_LEAGUE)
        if self.scope_id != expected_scope.scope_id:
            raise ValueError("Observation must use the policy-supported Belgian Fixture Scope.")
        for name, value in (
            ("Home source name", self.home_source_name),
            ("Away source name", self.away_source_name),
            ("Resolved home team ID", self.home_team_id),
            ("Resolved away team ID", self.away_team_id),
        ):
            _require_text(value, name)
        if self.home_team_id == self.away_team_id:
            raise ValueError("Home and away teams must resolve to different canonical teams.")
        if self.kickoff_precision == "DATE":
            if self.kickoff_utc is not None:
                raise ValueError("DATE precision cannot contain a kickoff UTC instant.")
            _date_text(self.source_local_date, "Source kickoff date")
        elif self.kickoff_precision == "INSTANT":
            if self.kickoff_utc is None:
                raise ValueError("INSTANT precision requires a kickoff UTC instant.")
            _canonical_utc(self.kickoff_utc, "Kickoff UTC")
            _date_text(self.source_local_date, "Source kickoff date")
            local_date = (
                datetime.fromisoformat(self.kickoff_utc)
                .astimezone(
                    _source_timezone(
                        league_by_key(self.league_key).timezone,
                        date.fromisoformat(self.source_local_date),
                    )
                )
                .date()
                .isoformat()
            )
            if local_date != self.source_local_date:
                raise ValueError("Source local date does not match the Belgian kickoff date.")
        else:
            raise ValueError("Kickoff precision must be DATE or INSTANT.")
        if self.fixture_status not in _STATUS_VALUES:
            raise ValueError("Fixture status must be SCHEDULED, POSTPONED, or CANCELLED.")
        _require_text(self.publisher_id, "Publisher ID")
        _require_text(self.publisher_name, "Publisher name")
        _require_text(self.competition_id, "Competition ID")
        _require_text(self.competition_name, "Competition name")
        _require_text(self.title_or_publication_id, "Publication title", maximum=512)
        if self.publication_date is not None:
            _date_text(self.publication_date, "Publication date")
        _require_text(self.operator_id, "Operator ID", maximum=_MAX_OPERATOR_ID)
        _canonical_utc(self.observed_at_utc, "Observation timestamp")
        policy = operator_fixture_observation_policy_v1()
        if (
            self.policy_id != policy.policy_id
            or self.policy_version != policy.policy_version
            or self.policy_digest != policy.digest
            or self.publisher_id != policy.publisher_id
            or self.publisher_name != policy.publisher_name
            or self.competition_id != policy.competition_id
            or self.competition_name != policy.competition_name
        ):
            raise ValueError("Observation publisher, competition, or policy identity is invalid.")
        policy.validate_publication(
            publication_id=self.publication_id,
            publication_type=self.publication_type,
            official_url=self.official_url,
        )
        if (
            self.mode != "RESEARCH_ONLY"
            or self.access_method != "MANUAL_CITATION"
            or self.source_class != "OFFICIAL_COMPETITION"
        ):
            raise ValueError("Observation source classification is invalid.")
        expected_digest = _observation_digest(self)
        if self.digest and self.digest != expected_digest:
            raise ValueError("Observation digest does not match its canonical facts.")
        object.__setattr__(self, "digest", expected_digest)


def _observation_body(observation: OperatorOfficialFixtureObservation) -> dict[str, object]:
    return {
        item.name: getattr(observation, item.name)
        for item in fields(OperatorOfficialFixtureObservation)
        if item.name != "digest"
    }


def _observation_digest(observation: OperatorOfficialFixtureObservation) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(_observation_body(observation))).hexdigest()}"


def operator_fixture_observation_to_canonical_json(
    observation: OperatorOfficialFixtureObservation,
) -> str:
    if type(observation) is not OperatorOfficialFixtureObservation:
        raise TypeError("Expected an OperatorOfficialFixtureObservation value.")
    payload = {"observation": _observation_body(observation), "digest": observation.digest}
    return _canonical_json(payload).decode("utf-8")


def operator_fixture_observation_from_canonical_json(
    content: str,
) -> OperatorOfficialFixtureObservation:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Malformed Operator Official Fixture Observation JSON.") from error
    if not isinstance(payload, dict) or set(payload) != {"observation", "digest"}:
        raise ValueError("Malformed Operator Official Fixture Observation envelope.")
    body = payload["observation"]
    expected_fields = {
        item.name for item in fields(OperatorOfficialFixtureObservation) if item.name != "digest"
    }
    if not isinstance(body, dict) or set(body) != expected_fields:
        raise ValueError("Malformed Operator Official Fixture Observation fields.")
    if not isinstance(payload["digest"], str):
        raise ValueError("Observation digest is missing.")
    observation = OperatorOfficialFixtureObservation(**body, digest=payload["digest"])
    canonical = operator_fixture_observation_to_canonical_json(observation)
    if canonical != content:
        raise ValueError("Observation artifact is not canonical JSON.")
    return observation


@dataclass(frozen=True)
class OfficialFixtureObservationInput:
    league_key: str
    season: str
    friday: str
    home: str
    away: str
    kickoff: str
    status: str
    official_url: str
    publication_id: str
    publication_type: str
    title: str
    publication_date: str | None
    operator_id: str


@dataclass(frozen=True)
class PersistedOfficialFixtureObservation:
    observation: OperatorOfficialFixtureObservation
    artifact_digest: str
    capture_id: str
    fixture_id: str
    revision_id: str
    import_result: ImportResult


class OperatorFixtureObservationIntegrityError(ValueError):
    """A saved LF05 artifact or its ordinary fixture provenance is inconsistent."""


class OperatorFixtureObservationRepository:
    """Record and replay one immutable operator-cited fixture fact at a time."""

    def __init__(self, store: Store, *, private_root: Path) -> None:
        self._store = store
        self._private_root = private_root.resolve()
        self._artifacts = ArtifactStore(store)
        self._importer = FixtureHistoryImporter(store, private_root=self._private_root)

    def record(self, value: OfficialFixtureObservationInput) -> PersistedOfficialFixtureObservation:
        policy = operator_fixture_observation_policy_v1()
        if value.league_key != policy.league_key or value.season != policy.season:
            raise ValueError("No official fixture observation policy supports this scope.")
        scopes = fixture_scopes_for_matchweek(value.friday, season=value.season)
        scope = next(item for item in scopes if item.league_key == value.league_key)
        league = league_by_key(value.league_key)
        policy.validate_publication(
            publication_id=value.publication_id,
            publication_type=value.publication_type,
            official_url=value.official_url,
        )
        _require_text(value.title, "Publication title", maximum=512)
        if value.publication_date is not None:
            _date_text(value.publication_date, "Publication date")
        _require_text(value.operator_id, "Operator ID", maximum=_MAX_OPERATOR_ID)
        if value.status not in _STATUS_VALUES:
            raise ValueError("Fixture status must be SCHEDULED, POSTPONED, or CANCELLED.")
        _require_text(value.home, "Home source name")
        _require_text(value.away, "Away source name")
        kickoff_precision, kickoff_utc, source_date, local_text = _parse_kickoff(
            value.kickoff, league
        )
        home = self._resolve_team(league, value.season, value.home, "Home")
        away = self._resolve_team(league, value.season, value.away, "Away")
        if home.canonical_team_id == away.canonical_team_id:
            raise ValueError("Home and away names must resolve to different canonical teams.")
        observation = OperatorOfficialFixtureObservation(
            contract_version=OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION,
            schema_version=OPERATOR_FIXTURE_OBSERVATION_SCHEMA_VERSION,
            league_key=value.league_key,
            season=value.season,
            matchweek_friday=value.friday,
            scope_id=scope.scope_id,
            home_source_name=value.home,
            away_source_name=value.away,
            home_team_id=_confirmed_team_id(home),
            away_team_id=_confirmed_team_id(away),
            kickoff_precision=kickoff_precision,
            kickoff_utc=kickoff_utc,
            source_local_date=source_date,
            fixture_status=value.status,
            publisher_id=policy.publisher_id,
            publisher_name=policy.publisher_name,
            competition_id=policy.competition_id,
            competition_name=policy.competition_name,
            publication_id=value.publication_id,
            publication_type=value.publication_type,
            official_url=value.official_url,
            title_or_publication_id=value.title,
            publication_date=value.publication_date,
            operator_id=value.operator_id,
            observed_at_utc=datetime.now(UTC).isoformat(),
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_digest=policy.digest,
            mode="RESEARCH_ONLY",
            access_method="MANUAL_CITATION",
            source_class="OFFICIAL_COMPETITION",
        )
        # The v1 event digest includes observation time. Command replay instead
        # compares the facts, retaining canonical team and publication identities.
        fact_fields = tuple(
            item.name
            for item in fields(OperatorOfficialFixtureObservation)
            if item.name not in {"observed_at_utc", "digest"}
        )
        matches = tuple(
            record
            for record in self.list_for_scope(scope.scope_id)
            if all(
                getattr(record.observation, name) == getattr(observation, name)
                for name in fact_fields
            )
        )
        if len(matches) > 1:
            raise OperatorFixtureObservationIntegrityError(
                "Multiple existing observations match the same logical fixture fact."
            )
        if matches:
            return matches[0]
        return self.persist(observation, kickoff_local_text=local_text)

    def persist(
        self,
        observation: OperatorOfficialFixtureObservation,
        *,
        kickoff_local_text: str | None = None,
    ) -> PersistedOfficialFixtureObservation:
        """Persist an exact event after rechecking LF03 identity against this store."""
        league = league_by_key(observation.league_key)
        home = self._resolve_team(league, observation.season, observation.home_source_name, "Home")
        away = self._resolve_team(league, observation.season, observation.away_source_name, "Away")
        if (
            _confirmed_team_id(home) != observation.home_team_id
            or _confirmed_team_id(away) != observation.away_team_id
        ):
            raise ValueError("Stored canonical team identities no longer match LF03 resolution.")
        parsed_instant: datetime | None = None
        if observation.kickoff_precision == "INSTANT":
            assert observation.kickoff_utc is not None
            parsed_instant = datetime.fromisoformat(observation.kickoff_utc)
            if kickoff_local_text is None:
                kickoff_local_text = parsed_instant.astimezone(
                    _source_timezone(
                        league.timezone, date.fromisoformat(observation.source_local_date)
                    )
                ).isoformat()
        else:
            kickoff_local_text = observation.source_local_date
        row_key = f"official-observation:{observation.digest}"
        row = ParsedRow(
            source_row_key=row_key,
            home_team=observation.home_source_name,
            away_team=observation.away_source_name,
            kickoff_utc=parsed_instant,
            kickoff_local_date=date.fromisoformat(observation.source_local_date),
            kickoff_local_text=kickoff_local_text,
            kickoff_precision=observation.kickoff_precision,
            fields={},
            raw_fields={},
            explicit_fixture_status=observation.fixture_status,
        )
        content = operator_fixture_observation_to_canonical_json(observation).encode("utf-8")
        capture = SourceCaptureInput(
            source_url=observation.official_url,
            retrieved_at_utc=observation.observed_at_utc,
            observed_terms="RESEARCH_ONLY:MANUAL_CITATION",
            content_type=OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE,
            cache_key=f"lf05:{observation.scope_id}:{observation.digest}",
        )
        result = self._importer.import_dataset(
            ParsedDataset(
                SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION,
                league,
                observation.season,
                (row,),
                OPERATOR_FIXTURE_OBSERVATION_CONTRACT_VERSION,
            ),
            content,
            capture,
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        record = verify_operator_fixture_observation_capture(
            self._store,
            result.source_capture_id,
            expected_scope_id=observation.scope_id,
        )
        if record.observation != observation:
            raise OperatorFixtureObservationIntegrityError(
                "Persisted observation does not match the requested immutable event."
            )
        return PersistedOfficialFixtureObservation(
            observation=record.observation,
            artifact_digest=record.artifact_digest,
            capture_id=record.capture_id,
            fixture_id=record.fixture_id,
            revision_id=record.revision_id,
            import_result=result,
        )

    def get(self, artifact_digest: str) -> PersistedOfficialFixtureObservation:
        rows = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT c.capture_id
            FROM source_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            WHERE s.source_key = ? AND c.artifact_digest = ?
            ORDER BY c.capture_id
            """,
                (OPERATOR_FIXTURE_OBSERVATION_SOURCE_KEY, artifact_digest),
            )
            .fetchall()
        )
        if len(rows) != 1:
            raise OperatorFixtureObservationIntegrityError(
                "Exact observation artifact is missing or has ambiguous capture provenance."
            )
        record = verify_operator_fixture_observation_capture(self._store, str(rows[0][0]))
        return PersistedOfficialFixtureObservation(
            observation=record.observation,
            artifact_digest=record.artifact_digest,
            capture_id=record.capture_id,
            fixture_id=record.fixture_id,
            revision_id=record.revision_id,
            import_result=ImportResult(
                source_capture_id=record.capture_id,
                source_digest=record.artifact_digest,
                league_key=record.observation.league_key,
                season=record.observation.season,
                fixtures_seen=1,
                fixtures_imported=0,
                revisions_appended=0,
                statistics_imported=0,
                unknown_fields=0,
                duplicate_rows=1,
                unresolved_rows=0,
                conflicts=0,
                from_existing_capture=True,
            ),
        )

    def list_for_scope(self, scope_id: str) -> tuple[PersistedOfficialFixtureObservation, ...]:
        prefix = f"lf05:{scope_id}:"
        rows = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT c.capture_id
            FROM source_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            WHERE s.source_key = ? AND substr(c.cache_key, 1, ?) = ?
            ORDER BY c.retrieved_at_utc, c.capture_id
            """,
                (OPERATOR_FIXTURE_OBSERVATION_SOURCE_KEY, len(prefix), prefix),
            )
            .fetchall()
        )
        records: list[PersistedOfficialFixtureObservation] = []
        for row in rows:
            record = verify_operator_fixture_observation_capture(
                self._store, str(row[0]), expected_scope_id=scope_id
            )
            records.append(
                PersistedOfficialFixtureObservation(
                    observation=record.observation,
                    artifact_digest=record.artifact_digest,
                    capture_id=record.capture_id,
                    fixture_id=record.fixture_id,
                    revision_id=record.revision_id,
                    import_result=ImportResult(
                        source_capture_id=record.capture_id,
                        source_digest=record.artifact_digest,
                        league_key=record.observation.league_key,
                        season=record.observation.season,
                        fixtures_seen=1,
                        fixtures_imported=0,
                        revisions_appended=0,
                        statistics_imported=0,
                        unknown_fields=0,
                        duplicate_rows=1,
                        unresolved_rows=0,
                        conflicts=0,
                        from_existing_capture=True,
                    ),
                )
            )
        return tuple(records)

    def _resolve_team(
        self, league: LeagueConfig, season: str, source_name: str, label: str
    ) -> TeamResolution:
        resolution = self._importer.resolve_existing_team(league, season, source_name)
        if resolution.state is MappingState.UNKNOWN:
            raise ValueError(f"{label} team {source_name!r} is unknown in {league.name}.")
        if resolution.state is MappingState.AMBIGUOUS:
            raise ValueError(f"{label} team {source_name!r} is ambiguous in {league.name}.")
        return resolution


def _confirmed_team_id(resolution: TeamResolution) -> str:
    if resolution.state is not MappingState.CONFIRMED or resolution.canonical_team_id is None:
        raise ValueError("A team must resolve to one existing canonical identity.")
    return resolution.canonical_team_id


def _parse_kickoff(value: str, league: LeagueConfig) -> tuple[str, str | None, str, str | None]:
    _require_text(value, "Kickoff")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        source_date = _date_text(value, "Kickoff date")
        return "DATE", None, source_date, source_date
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            "Kickoff must be YYYY-MM-DD or an offset-aware ISO-8601 instant."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("INSTANT kickoff must include a UTC offset.")
    utc_value = parsed.astimezone(UTC).isoformat()
    local = datetime.fromisoformat(utc_value).astimezone(
        _source_timezone(league.timezone, parsed.date())
    )
    return "INSTANT", utc_value, local.date().isoformat(), local.isoformat()


@dataclass(frozen=True)
class VerifiedOperatorFixtureObservationCapture:
    observation: OperatorOfficialFixtureObservation
    artifact_digest: str
    capture_id: str
    fixture_id: str
    revision_id: str
    source_row_key: str


def verify_operator_fixture_observation_capture(
    store: Store,
    capture_id: str,
    *,
    expected_scope_id: str | None = None,
) -> VerifiedOperatorFixtureObservationCapture:
    """Verify one LF05 artifact, policy, identity, and ordinary T04 provenance chain."""
    connection = store._connection_for_repository()
    row = connection.execute(
        """
        SELECT c.source_id, c.cache_key, c.locator, c.access_method, c.retrieved_at_utc,
               c.content_type, c.content_sha256, c.byte_length, c.artifact_digest,
               c.retention_status, c.observed_terms, c.terms_reference, c.rights_json,
               c.collector_version, s.source_key, s.canonical_name, s.owner, s.source_class,
               s.access_method, s.base_locator, s.allowed_use, s.retention_status,
               s.redistributable, s.terms_reference
        FROM source_captures AS c
        JOIN source_identities AS s ON s.source_id = c.source_id
        WHERE c.capture_id = ?
        """,
        (capture_id,),
    ).fetchone()
    if row is None:
        raise OperatorFixtureObservationIntegrityError("Observation source capture is missing.")
    expected_source_id = deterministic_identifier("source", OPERATOR_FIXTURE_OBSERVATION_SOURCE_KEY)
    if (
        str(row[0]) != expected_source_id
        or str(row[14]) != OPERATOR_FIXTURE_OBSERVATION_SOURCE_KEY
        or str(row[15]) != "Pro League official publication, manual citation"
        or str(row[16]) != "Pro League"
        or str(row[17]) != "OFFICIAL_COMPETITION"
        or str(row[18]) != "MANUAL_CITATION"
        or str(row[19]) != "https://www.proleague.be/"
        or str(row[20]) != "RESEARCH_ONLY"
        or str(row[21]) != "RETAIN_PRIVATE"
        or bool(row[22])
        or str(row[23]) != "matchvet:operator-official-fixture-observation:1"
        or str(row[3]) != "MANUAL_CITATION"
        or str(row[5]) != OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE
        or str(row[9]) != "RETAIN_PRIVATE"
        or str(row[10]) != "RESEARCH_ONLY:MANUAL_CITATION"
        or str(row[11]) != "matchvet:operator-official-fixture-observation:1"
        or str(row[13]) != "matchvet-t06-v1"
    ):
        raise OperatorFixtureObservationIntegrityError(
            "Observation source identity or capture classification is invalid."
        )
    try:
        rights = json.loads(str(row[12]))
    except json.JSONDecodeError as error:
        raise OperatorFixtureObservationIntegrityError(
            "Observation source rights metadata is malformed."
        ) from error
    expected_rights = {
        "allowed_use": "RESEARCH_ONLY",
        "redistributable": False,
        "retention_status": "RETAIN_PRIVATE",
        "source_kind": SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION.value,
    }
    if rights != expected_rights:
        raise OperatorFixtureObservationIntegrityError(
            "Observation source rights metadata is not the LF05 policy classification."
        )
    artifact_digest = str(row[8])
    try:
        artifact = ArtifactStore(store).verify_artifact(artifact_digest)
        if (
            artifact.media_type != OPERATOR_FIXTURE_OBSERVATION_MEDIA_TYPE
            or artifact.retention_class != "PROTECTED"
        ):
            raise OperatorFixtureObservationIntegrityError(
                "Observation artifact type or retention class is invalid."
            )
        content = ArtifactStore(store).read_artifact(artifact_digest)
        observation = operator_fixture_observation_from_canonical_json(content.decode("utf-8"))
    except OperatorFixtureObservationIntegrityError:
        raise
    except (ArtifactError, UnicodeDecodeError, ValueError) as error:
        raise OperatorFixtureObservationIntegrityError(
            "Observation artifact is missing, corrupt, or unsupported."
        ) from error
    if (
        artifact_digest != str(row[6])
        or len(content) != int(row[7])
        or artifact_digest != sha256_bytes(content)
        or str(row[2]) != observation.official_url
        or str(row[4]) != observation.observed_at_utc
        or str(row[1]) != f"lf05:{observation.scope_id}:{observation.digest}"
        or (expected_scope_id is not None and observation.scope_id != expected_scope_id)
    ):
        raise OperatorFixtureObservationIntegrityError(
            "Observation artifact citation, scope, timestamp, or capture digest differs."
        )
    expected_capture_id = deterministic_identifier(
        "source_capture",
        f"{expected_source_id}:{row[1]}:{artifact_digest}:{observation.observed_at_utc}",
    )
    if capture_id != expected_capture_id:
        raise OperatorFixtureObservationIntegrityError(
            "Observation source capture identity does not match its immutable event."
        )
    _verify_observation_fixture_provenance(store, capture_id, observation)
    return VerifiedOperatorFixtureObservationCapture(
        observation=observation,
        artifact_digest=artifact_digest,
        capture_id=capture_id,
        fixture_id=deterministic_identifier(
            "fixture",
            f"{observation.league_key}:{observation.season}:"
            f"{observation.home_team_id}:{observation.away_team_id}",
        ),
        revision_id=_observation_revision_id(observation),
        source_row_key=f"official-observation:{observation.digest}",
    )


def _observation_revision_payload(
    observation: OperatorOfficialFixtureObservation,
) -> dict[str, object]:
    return {
        "fixture_status": observation.fixture_status,
        "kickoff_local_text": _observation_local_text(observation),
        "kickoff_precision": observation.kickoff_precision,
        "kickoff_state": "OBSERVED",
        "kickoff_utc": observation.kickoff_utc,
        "source_round": None,
    }


def _observation_local_text(observation: OperatorOfficialFixtureObservation) -> str:
    if observation.kickoff_precision == "DATE":
        return observation.source_local_date
    assert observation.kickoff_utc is not None
    league = league_by_key(observation.league_key)
    return (
        datetime.fromisoformat(observation.kickoff_utc)
        .astimezone(
            _source_timezone(league.timezone, date.fromisoformat(observation.source_local_date))
        )
        .isoformat()
    )


def _observation_revision_id(observation: OperatorOfficialFixtureObservation) -> str:
    fixture_id = deterministic_identifier(
        "fixture",
        f"{observation.league_key}:{observation.season}:"
        f"{observation.home_team_id}:{observation.away_team_id}",
    )
    revision_digest = sha256_bytes(_canonical_json(_observation_revision_payload(observation)))
    return deterministic_identifier("fixture_revision", f"{fixture_id}:{revision_digest}")


def _verify_observation_fixture_provenance(
    store: Store,
    capture_id: str,
    observation: OperatorOfficialFixtureObservation,
) -> None:
    league = league_by_key(observation.league_key)
    importer = FixtureHistoryImporter(store, private_root=store.path.parent)
    for label, source_name, expected_id in (
        ("Home", observation.home_source_name, observation.home_team_id),
        ("Away", observation.away_source_name, observation.away_team_id),
    ):
        resolution = importer.resolve_existing_team(league, observation.season, source_name)
        if (
            resolution.state is not MappingState.CONFIRMED
            or resolution.canonical_team_id != expected_id
        ):
            raise OperatorFixtureObservationIntegrityError(
                f"{label} canonical identity no longer matches LF03 resolution."
            )
    fixture_id = deterministic_identifier(
        "fixture",
        f"{observation.league_key}:{observation.season}:"
        f"{observation.home_team_id}:{observation.away_team_id}",
    )
    expected_revision_id = _observation_revision_id(observation)
    expected_payload = _observation_revision_payload(observation)
    row_key = f"official-observation:{observation.digest}"
    rows = (
        store._connection_for_repository()
        .execute(
            """
        SELECT assertion_id, predicate, raw_field_name, raw_value_json,
               normalized_value_json, evidence_state, subject_kind, subject_key,
               event_time_utc, effective_time_utc
        FROM source_assertions
        WHERE capture_id = ? AND source_row_key = ?
        ORDER BY predicate
        """,
            (capture_id, row_key),
        )
        .fetchall()
    )
    expected_predicates = {"home_team", "away_team", "kickoff", "fixture_status"}
    assertions = {str(item[1]): item for item in rows}
    if len(rows) != 4 or set(assertions) != expected_predicates:
        raise OperatorFixtureObservationIntegrityError(
            "Observation capture does not contain exactly its four fixture assertions."
        )
    expected_assertions: dict[str, tuple[str, str, str | None, str | None]] = {
        "home_team": ("team1", observation.home_source_name, observation.home_source_name, None),
        "away_team": ("team2", observation.away_source_name, observation.away_source_name, None),
        "kickoff": (
            "Date/Time",
            _observation_local_text(observation),
            observation.kickoff_utc or observation.source_local_date,
            observation.kickoff_utc,
        ),
        "fixture_status": (
            "FixtureStatus",
            observation.fixture_status,
            observation.fixture_status,
            None,
        ),
    }
    assertion_ids: set[str] = set()
    for predicate, fact in expected_assertions.items():
        item = assertions[predicate]
        assertion_id = deterministic_identifier(
            "source_assertion", f"{capture_id}:{row_key}:{predicate}"
        )
        assertion_ids.add(assertion_id)
        if (
            str(item[0]) != assertion_id
            or str(item[2]) != fact[0]
            or json.loads(str(item[3])) != fact[1]
            or json.loads(str(item[4])) != fact[2]
            or str(item[5]) != "OBSERVED"
            or str(item[6]) != "FIXTURE"
            or str(item[7]) != fixture_id
            or (None if item[8] is None else str(item[8])) != fact[3]
            or (None if item[9] is None else str(item[9])) != fact[3]
        ):
            raise OperatorFixtureObservationIntegrityError(
                f"Observation {predicate} assertion does not match the canonical event."
            )
    fixture = (
        store._connection_for_repository()
        .execute(
            """
        SELECT f.league_id, f.season_id, f.home_team_id, f.away_team_id, f.identity_state,
               r.revision_id, r.revision_digest, r.kickoff_state, r.kickoff_utc,
               r.kickoff_local_text, r.kickoff_precision, r.fixture_status,
               r.source_round, r.observed_at_utc
        FROM fixtures AS f
        JOIN fixture_revisions AS r ON r.fixture_id = f.fixture_id
        WHERE f.fixture_id = ? AND r.revision_id = ?
        """,
            (fixture_id, expected_revision_id),
        )
        .fetchone()
    )
    if fixture is None:
        raise OperatorFixtureObservationIntegrityError(
            "Observation Fixture or exact Fixture Revision is missing."
        )
    expected_revision_digest = sha256_bytes(_canonical_json(expected_payload))
    if (
        str(fixture[0]) != deterministic_identifier("league", observation.league_key)
        or str(fixture[1])
        != deterministic_identifier(
            "competition_season", f"{observation.league_key}:{observation.season}"
        )
        or str(fixture[2]) != observation.home_team_id
        or str(fixture[3]) != observation.away_team_id
        or str(fixture[4]) != "CONFIRMED"
        or str(fixture[5]) != expected_revision_id
        or str(fixture[6]) != expected_revision_digest
        or str(fixture[7]) != "OBSERVED"
        or (None if fixture[8] is None else str(fixture[8])) != observation.kickoff_utc
        or str(fixture[9]) != _observation_local_text(observation)
        or str(fixture[10]) != observation.kickoff_precision
        or str(fixture[11]) != observation.fixture_status
        or fixture[12] is not None
    ):
        raise OperatorFixtureObservationIntegrityError(
            "Observation Fixture Revision facts do not match its canonical event."
        )
    links = (
        store._connection_for_repository()
        .execute(
            """
        SELECT assertion_id FROM fixture_revision_assertions
        WHERE revision_id = ?
        """,
            (expected_revision_id,),
        )
        .fetchall()
    )
    if not assertion_ids.issubset({str(link[0]) for link in links}):
        raise OperatorFixtureObservationIntegrityError(
            "Observation assertions are not linked to their Fixture Revision."
        )

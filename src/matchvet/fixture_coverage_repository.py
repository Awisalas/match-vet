"""Immutable persistence for complete F01 Fixture Coverage Assessments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from matchvet.fixture_coverage import (
    FIXTURE_COVERAGE_CONTRACT_VERSION,
    FIXTURE_COVERAGE_SCHEMA_VERSION,
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    FixtureIdentityState,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    ScopeCoverageState,
    fixture_coverage_assessment_from_canonical_json,
    fixture_coverage_assessment_to_canonical_json,
    fixture_scopes_for_matchweek,
)
from matchvet.ingestion import TARGET_LEAGUES
from matchvet.store import Store, StoreTransaction

if TYPE_CHECKING:
    import sqlite3

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ASSESSMENT_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class FixtureCoverageIntegrityError(ValueError):
    """F03 found an unsupported assessment or inconsistent stored provenance."""

    code = "MV-F03-ASSESSMENT-INTEGRITY"


class FixtureCoveragePersistenceError(RuntimeError):
    """F02 could not durably save the assessment it produced."""

    code = "MV-F03-PERSISTENCE-FAILED"


@dataclass(frozen=True)
class _AssessmentMetadata:
    season: str
    friday: str
    schedule_state: str
    freshness_policy_id: str | None


@dataclass(frozen=True)
class _AssessmentLinks:
    revisions: tuple[tuple[str, str, str, str], ...]
    captures: tuple[tuple[str, str], ...]
    assertions: tuple[tuple[str, str], ...]


class FixtureCoverageRepository:
    """Save, load, and enumerate immutable F01 assessment values."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def persist(self, assessment: FixtureCoverageAssessment) -> str:
        """Validate all V1 links and atomically append one complete F01 value."""
        payload = self._canonical_payload(assessment)
        metadata = _assessment_metadata(assessment)
        with self._store.transaction() as transaction:
            links = _assessment_links(transaction, assessment)
            existing = transaction.execute(
                """
                SELECT assessment_json, contract_version, assessment_schema_version,
                       season, matchweek_friday, schedule_state, freshness_policy_id
                FROM fixture_coverage_assessments
                WHERE assessment_digest = ?
                """,
                (assessment.digest,),
            ).fetchone()
            if existing is not None:
                actual_root = (
                    str(existing[0]),
                    str(existing[1]),
                    int(existing[2]),
                    str(existing[3]),
                    str(existing[4]),
                    str(existing[5]),
                    None if existing[6] is None else str(existing[6]),
                )
                expected_root = (
                    payload,
                    assessment.contract_version,
                    assessment.schema_version,
                    metadata.season,
                    metadata.friday,
                    metadata.schedule_state,
                    metadata.freshness_policy_id,
                )
                if (
                    actual_root != expected_root
                    or self._stored_links(transaction, assessment.digest) != links
                ):
                    raise FixtureCoverageIntegrityError(
                        "Stored values for this Fixture Coverage digest do not match F01."
                    )
                return assessment.digest

            transaction.execute(
                """
                INSERT INTO fixture_coverage_assessments (
                    assessment_digest, assessment_json, contract_version,
                    assessment_schema_version, season, matchweek_friday,
                    schedule_state, freshness_policy_id, first_persisted_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.digest,
                    payload,
                    assessment.contract_version,
                    assessment.schema_version,
                    metadata.season,
                    metadata.friday,
                    metadata.schedule_state,
                    metadata.freshness_policy_id,
                    datetime.now(UTC).isoformat(timespec="microseconds"),
                ),
            )
            for scope_id, fixture_id, revision_id, revision_digest in links.revisions:
                transaction.execute(
                    """
                    INSERT INTO fixture_coverage_assessment_revisions (
                        assessment_digest, scope_id, fixture_id, revision_id,
                        expected_revision_digest
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (assessment.digest, scope_id, fixture_id, revision_id, revision_digest),
                )
            for capture_id, capture_digest in links.captures:
                transaction.execute(
                    """
                    INSERT INTO fixture_coverage_assessment_captures (
                        assessment_digest, capture_id, expected_content_sha256
                    ) VALUES (?, ?, ?)
                    """,
                    (assessment.digest, capture_id, capture_digest),
                )
            for assertion_id, capture_id in links.assertions:
                transaction.execute(
                    """
                    INSERT INTO fixture_coverage_assessment_assertions (
                        assessment_digest, assertion_id, source_capture_id
                    ) VALUES (?, ?, ?)
                    """,
                    (assessment.digest, assertion_id, capture_id),
                )
        return assessment.digest

    def get(self, assessment_digest: str) -> FixtureCoverageAssessment | None:
        """Load one exact immutable F01 value by its assessment digest."""
        if _ASSESSMENT_DIGEST_RE.fullmatch(assessment_digest) is None:
            raise ValueError("Fixture Coverage assessment digest must be a sha256 digest.")
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT assessment_json, contract_version, assessment_schema_version,
                   season, matchweek_friday, schedule_state, freshness_policy_id
            FROM fixture_coverage_assessments
            WHERE assessment_digest = ?
            """,
            (assessment_digest,),
        ).fetchone()
        if row is None:
            return None
        try:
            assessment = fixture_coverage_assessment_from_canonical_json(str(row[0]))
            metadata = _assessment_metadata(assessment)
            expected_root = (
                assessment.contract_version,
                assessment.schema_version,
                metadata.season,
                metadata.friday,
                metadata.schedule_state,
                metadata.freshness_policy_id,
            )
            actual_root = (
                str(row[1]),
                int(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                None if row[6] is None else str(row[6]),
            )
            if assessment.digest != assessment_digest or actual_root != expected_root:
                raise FixtureCoverageIntegrityError(
                    "Fixture Coverage row identity or derived values do not match its payload."
                )
            expected_links = _assessment_links(connection, assessment)
            if self._stored_links(connection, assessment_digest) != expected_links:
                raise FixtureCoverageIntegrityError(
                    "Fixture Coverage payload provenance does not match its relational links."
                )
            return assessment
        except FixtureCoverageIntegrityError:
            raise
        except (FixtureCoveragePayloadError, TypeError, ValueError, IndexError) as error:
            raise FixtureCoverageIntegrityError(
                "Fixture Coverage payload or provenance is corrupt."
            ) from error

    def list_for_matchweek(self, season: str, friday: str) -> tuple[FixtureCoverageAssessment, ...]:
        """List all assessments for one Matchweek in stable persistence order."""
        if not season.strip():
            raise ValueError("Matchweek season must not be empty.")
        fixture_scopes_for_matchweek(friday, season=season)
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT assessment_digest
            FROM fixture_coverage_assessments
            WHERE season = ? AND matchweek_friday = ?
            ORDER BY first_persisted_at_utc, assessment_digest
            """,
            (season, friday),
        ).fetchall()
        assessments = tuple(self.get(str(row[0])) for row in rows)
        if any(assessment is None for assessment in assessments):
            raise FixtureCoverageIntegrityError("Fixture Coverage history contains a missing row.")
        return cast(tuple[FixtureCoverageAssessment, ...], assessments)

    def _canonical_payload(self, assessment: FixtureCoverageAssessment) -> str:
        try:
            if assessment.digest and _ASSESSMENT_DIGEST_RE.fullmatch(assessment.digest) is None:
                raise FixtureCoverageIntegrityError("Fixture Coverage digest has an invalid shape.")
            payload = fixture_coverage_assessment_to_canonical_json(assessment)
            if assessment.digest != _assessment_digest_from_payload(payload):
                raise FixtureCoverageIntegrityError(
                    "Fixture Coverage digest does not match its canonical F01 value."
                )
            return payload
        except FixtureCoveragePayloadError as error:
            raise FixtureCoverageIntegrityError(str(error)) from error

    def _stored_links(
        self, connection: StoreTransaction | sqlite3.Connection, assessment_digest: str
    ) -> _AssessmentLinks:
        revisions = connection.execute(
            """
            SELECT scope_id, fixture_id, revision_id, expected_revision_digest
            FROM fixture_coverage_assessment_revisions
            WHERE assessment_digest = ?
            ORDER BY scope_id, fixture_id, revision_id, expected_revision_digest
            """,
            (assessment_digest,),
        ).fetchall()
        captures = connection.execute(
            """
            SELECT capture_id, expected_content_sha256
            FROM fixture_coverage_assessment_captures
            WHERE assessment_digest = ?
            ORDER BY capture_id, expected_content_sha256
            """,
            (assessment_digest,),
        ).fetchall()
        assertions = connection.execute(
            """
            SELECT assertion_id, source_capture_id
            FROM fixture_coverage_assessment_assertions
            WHERE assessment_digest = ?
            ORDER BY assertion_id, source_capture_id
            """,
            (assessment_digest,),
        ).fetchall()
        return _AssessmentLinks(
            revisions=tuple(
                (str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in revisions
            ),
            captures=tuple((str(row[0]), str(row[1])) for row in captures),
            assertions=tuple((str(row[0]), str(row[1])) for row in assertions),
        )


def _assessment_digest_from_payload(payload: str) -> str:
    from matchvet.fixture_coverage import fixture_coverage_assessment_from_canonical_json

    return fixture_coverage_assessment_from_canonical_json(payload).digest


def _assessment_metadata(assessment: FixtureCoverageAssessment) -> _AssessmentMetadata:
    if (
        assessment.contract_version != FIXTURE_COVERAGE_CONTRACT_VERSION
        or assessment.schema_version != FIXTURE_COVERAGE_SCHEMA_VERSION
    ):
        raise FixtureCoverageIntegrityError("Fixture Coverage F01 version is unsupported.")
    scopes = tuple(item.scope for item in assessment.scope_assessments)
    expected_leagues = tuple(league.key for league in TARGET_LEAGUES)
    if (
        len(scopes) != len(expected_leagues)
        or tuple(scope.league_key for scope in scopes) != expected_leagues
    ):
        raise FixtureCoverageIntegrityError(
            "Fixture Coverage Assessment must retain all seven ordered Fixture Scopes."
        )
    first_scope = scopes[0]
    if any(
        scope.season != first_scope.season or scope.matchweek_friday != first_scope.matchweek_friday
        for scope in scopes
    ):
        raise FixtureCoverageIntegrityError(
            "Fixture Coverage scopes must share one season and Matchweek Friday."
        )
    canonical_scopes = fixture_scopes_for_matchweek(
        first_scope.matchweek_friday, season=first_scope.season
    )
    if scopes != canonical_scopes:
        raise FixtureCoverageIntegrityError("Fixture Coverage Fixture Scopes are inconsistent.")
    if not isinstance(assessment.schedule_state, MatchweekScheduleState):
        raise FixtureCoverageIntegrityError("Fixture Coverage schedule state is unsupported.")
    return _AssessmentMetadata(
        season=first_scope.season,
        friday=first_scope.matchweek_friday,
        schedule_state=assessment.schedule_state.value,
        freshness_policy_id=assessment.freshness_policy_id,
    )


def _assessment_links(
    connection: StoreTransaction | sqlite3.Connection,
    assessment: FixtureCoverageAssessment,
) -> _AssessmentLinks:
    _assessment_metadata(assessment)
    scope_ids = {item.scope.scope_id for item in assessment.scope_assessments}
    attempts: dict[str, ProviderAttempt] = {}
    capture_digests: dict[str, str] = {}
    capture_scopes: dict[str, str] = {}

    def add_capture(capture_id: str, digest: str, scope_id: str) -> None:
        expected_digest = _sha256_value(digest, "source capture digest")
        previous_digest = capture_digests.setdefault(capture_id, expected_digest)
        previous_scope = capture_scopes.setdefault(capture_id, scope_id)
        if previous_digest != expected_digest or previous_scope != scope_id:
            raise FixtureCoverageIntegrityError(
                f"Source capture {capture_id} has conflicting F01 references."
            )

    for attempt in assessment.provider_attempts:
        if attempt.scope_id not in scope_ids or attempt.attempt_id in attempts:
            raise FixtureCoverageIntegrityError(
                "Fixture Coverage Provider Attempt is inconsistent."
            )
        attempts[attempt.attempt_id] = attempt
        if attempt.capture_id is not None and attempt.capture_digest is not None:
            add_capture(attempt.capture_id, attempt.capture_digest, attempt.scope_id)

    evidence_by_id: dict[str, ProviderCoverageEvidence] = {}
    for evidence in assessment.coverage_evidence:
        referenced_attempt = attempts.get(evidence.attempt_id)
        if (
            evidence.scope_id not in scope_ids
            or evidence.evidence_id in evidence_by_id
            or referenced_attempt is None
            or referenced_attempt.scope_id != evidence.scope_id
            or referenced_attempt.state is not ProviderAttemptState.CAPTURED
            or referenced_attempt.capture_id != evidence.capture_id
            or referenced_attempt.capture_digest != evidence.capture_digest
        ):
            raise FixtureCoverageIntegrityError(
                "Provider Coverage Evidence does not match its retained Provider Attempt."
            )
        evidence_by_id[evidence.evidence_id] = evidence
        add_capture(evidence.capture_id, evidence.capture_digest, evidence.scope_id)

    freshness_evidence_ids: set[str] = set()
    for result in assessment.freshness_results:
        if (
            result.evidence_id not in evidence_by_id
            or result.evidence_id in freshness_evidence_ids
            or result.policy_id != assessment.freshness_policy_id
        ):
            raise FixtureCoverageIntegrityError(
                "Coverage Freshness Result does not match its evidence or policy identity."
            )
        freshness_evidence_ids.add(result.evidence_id)

    revision_links: list[tuple[str, str, str, str]] = []
    revision_by_id: dict[str, tuple[str, str]] = {}
    assertion_contexts: dict[str, list[tuple[str | None, tuple[str, ...], str | None]]] = {}
    for revision in assessment.fixture_revisions:
        if revision.scope_id not in scope_ids or revision.revision_id in revision_by_id:
            raise FixtureCoverageIntegrityError("Fixture Revision reference is inconsistent.")
        revision_digest = _sha256_value(revision.revision_digest, "fixture revision digest")
        revision_by_id[revision.revision_id] = (revision.fixture_id, revision.scope_id)
        revision_links.append(
            (revision.scope_id, revision.fixture_id, revision.revision_id, revision_digest)
        )
        for capture_id in revision.source_capture_ids:
            add_referenced_capture(capture_id, revision.scope_id, capture_scopes)
        _append_assertion_contexts(
            assertion_contexts,
            revision.source_assertion_ids,
            revision.source_capture_ids,
            revision.revision_id,
        )

    for identity in assessment.identity_resolutions:
        if identity.scope_id not in scope_ids:
            raise FixtureCoverageIntegrityError("Fixture Identity Resolution has an unknown scope.")
        for capture_id in identity.source_capture_ids:
            add_referenced_capture(capture_id, identity.scope_id, capture_scopes)
        _append_assertion_contexts(
            assertion_contexts,
            identity.source_assertion_ids,
            identity.source_capture_ids,
            None,
        )
        for identity_revision_id in identity.revision_ids:
            linked_revision = revision_by_id.get(identity_revision_id)
            if linked_revision is None or linked_revision[1] != identity.scope_id:
                raise FixtureCoverageIntegrityError(
                    "Fixture Identity Resolution references an unlinked revision."
                )
            if (
                identity.state is FixtureIdentityState.RESOLVED
                and linked_revision[0] != identity.canonical_fixture_id
            ):
                raise FixtureCoverageIntegrityError(
                    "Resolved identity and Fixture Revision disagree on fixture ID."
                )

    for scope_assessment in assessment.scope_assessments:
        scope_id = scope_assessment.scope.scope_id
        if not isinstance(scope_assessment.coverage_state, ScopeCoverageState):
            raise FixtureCoverageIntegrityError("Fixture Scope coverage state is unsupported.")
        expected_attempt_ids = tuple(
            sorted(
                attempt.attempt_id
                for attempt in assessment.provider_attempts
                if attempt.scope_id == scope_id
            )
        )
        expected_evidence_ids = tuple(
            sorted(
                evidence_id
                for evidence_id, evidence in evidence_by_id.items()
                if evidence.scope_id == scope_id
            )
        )
        expected_revisions = tuple(
            sorted(
                (
                    revision
                    for revision in assessment.fixture_revisions
                    if revision.scope_id == scope_id
                ),
                key=lambda item: item.revision_id,
            )
        )
        expected_blocker_ids = tuple(
            sorted(
                identity.candidate_id
                for identity in assessment.identity_resolutions
                if identity.scope_id == scope_id
                and identity.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
            )
        )
        expected_freshness = tuple(
            sorted(
                (
                    result
                    for result in assessment.freshness_results
                    if evidence_by_id[result.evidence_id].scope_id == scope_id
                ),
                key=lambda item: item.evidence_id,
            )
        )
        if (
            scope_assessment.provider_attempt_ids != expected_attempt_ids
            or scope_assessment.coverage_evidence_ids != expected_evidence_ids
            or scope_assessment.fixture_revisions != expected_revisions
            or scope_assessment.identity_blocker_candidate_ids != expected_blocker_ids
            or scope_assessment.freshness_results != expected_freshness
        ):
            raise FixtureCoverageIntegrityError(
                "Fixture Scope projections do not match the retained F01 assessment records."
            )

        current_ids = scope_assessment.current_coverage_evidence_ids
        stale_ids = scope_assessment.stale_coverage_evidence_ids
        scoped_freshness_ids = {result.evidence_id for result in expected_freshness}
        known_projected_ids = set(expected_evidence_ids) & scoped_freshness_ids
        if (
            current_ids != tuple(sorted(set(current_ids)))
            or stale_ids != tuple(sorted(set(stale_ids)))
            or not set(current_ids).issubset(known_projected_ids)
            or not set(stale_ids).issubset(known_projected_ids)
            or set(current_ids).intersection(stale_ids)
        ):
            raise FixtureCoverageIntegrityError(
                "Fixture Scope freshness projections reference inconsistent evidence."
            )

    assertion_links: set[tuple[str, str]] = set()
    for assertion_id, contexts in assertion_contexts.items():
        row = connection.execute(
            "SELECT capture_id FROM source_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ).fetchone()
        if row is None:
            raise FixtureCoverageIntegrityError(f"Source assertion {assertion_id} is missing.")
        capture_id = str(row[0])
        if capture_id not in capture_digests:
            raise FixtureCoverageIntegrityError(
                f"Source assertion {assertion_id} capture is not linked by the assessment."
            )
        for context_revision_id, capture_ids, _identity_scope in contexts:
            if capture_id not in capture_ids:
                raise FixtureCoverageIntegrityError(
                    f"Source assertion {assertion_id} capture does not match its F01 reference."
                )
            if (
                context_revision_id is not None
                and connection.execute(
                    """
                    SELECT 1 FROM fixture_revision_assertions
                    WHERE revision_id = ? AND assertion_id = ?
                    """,
                    (context_revision_id, assertion_id),
                ).fetchone()
                is None
            ):
                raise FixtureCoverageIntegrityError(
                    "Source assertion "
                    f"{assertion_id} is not linked to revision {context_revision_id}."
                )
            assertion_links.add((assertion_id, capture_id))

    for revision in assessment.fixture_revisions:
        stored = connection.execute(
            """
            SELECT fixture_id, revision_digest, source_capture_id
            FROM fixture_revisions
            WHERE revision_id = ?
            """,
            (revision.revision_id,),
        ).fetchone()
        if (
            stored is None
            or str(stored[0]) != revision.fixture_id
            or str(stored[1]) != _sha256_value(revision.revision_digest, "fixture revision digest")
            or str(stored[2]) not in revision.source_capture_ids
        ):
            raise FixtureCoverageIntegrityError(
                f"Fixture Revision {revision.revision_id} does not match its V1 identity."
            )
        for assertion_id in revision.source_assertion_ids:
            if (
                assertion_id,
                str(
                    connection.execute(
                        "SELECT capture_id FROM source_assertions WHERE assertion_id = ?",
                        (assertion_id,),
                    ).fetchone()[0]
                ),
            ) not in assertion_links:
                raise FixtureCoverageIntegrityError(
                    f"Fixture Revision {revision.revision_id} has an invalid assertion link."
                )

    for capture_id, expected_digest in capture_digests.items():
        actual = connection.execute(
            "SELECT content_sha256 FROM source_captures WHERE capture_id = ?", (capture_id,)
        ).fetchone()
        if actual is None or str(actual[0]) != expected_digest:
            raise FixtureCoverageIntegrityError(
                f"Source Capture {capture_id} does not match its V1 content digest."
            )

    capture_links = tuple(sorted(capture_digests.items()))
    return _AssessmentLinks(
        revisions=tuple(sorted(revision_links)),
        captures=capture_links,
        assertions=tuple(sorted(assertion_links)),
    )


def add_referenced_capture(capture_id: str, scope_id: str, capture_scopes: dict[str, str]) -> None:
    source_scope = capture_scopes.get(capture_id)
    if source_scope is None or source_scope != scope_id:
        raise FixtureCoverageIntegrityError(
            f"Source Capture {capture_id} is not retained by an attempt in the same scope."
        )


def _append_assertion_contexts(
    destination: dict[str, list[tuple[str | None, tuple[str, ...], str | None]]],
    assertion_ids: tuple[str, ...],
    capture_ids: tuple[str, ...],
    revision_id: str | None,
) -> None:
    for assertion_id in assertion_ids:
        destination.setdefault(assertion_id, []).append((revision_id, capture_ids, None))


def _sha256_value(value: str, label: str) -> str:
    digest = value.removeprefix("sha256:")
    if _SHA256_RE.fullmatch(digest) is None:
        raise FixtureCoverageIntegrityError(f"{label} must be a lowercase SHA-256 digest.")
    return digest

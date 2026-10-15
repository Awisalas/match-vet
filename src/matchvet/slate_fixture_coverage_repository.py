"""Immutable F01 persistence for the five-league interval successor."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from matchvet.fixture_coverage import ProviderAttemptState
from matchvet.ingestion import league_by_key, openfootball_text_url, openfootball_url
from matchvet.slate_fixture_coverage import (
    SlateFixtureCoverageAssessment,
    decode_slate_f01,
    encode_slate_f01,
)
from matchvet.store import Store, StoreTransaction

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class SlateFixtureCoverageIntegrityError(ValueError):
    """Stored slate F01 bytes or their indexed identity disagree."""


class SlateFixtureCoverageRepository:
    def __init__(self, store: Store, *, write_guard: Callable[[], object] | None = None) -> None:
        self._store = store
        self._write_guard = write_guard

    def persist(self, assessment: SlateFixtureCoverageAssessment) -> str:
        """Append one immutable interval assessment; identical replay is idempotent."""
        encoded = encode_slate_f01(assessment)
        if decode_slate_f01(encoded) != assessment:
            raise SlateFixtureCoverageIntegrityError("Slate F01 failed canonical round-trip.")
        if self._write_guard is not None:
            self._write_guard()
        window = assessment.slate_window
        active_scope = assessment.active_scope
        values = (
            assessment.digest,
            encoded,
            assessment.contract_version,
            assessment.schema_version,
            active_scope.contract_id,
            active_scope.digest,
            active_scope.season,
            window.contract_id,
            window.version,
            window.slate_id,
            window.digest,
            window.start_utc,
            window.end_utc,
            assessment.schedule_state.value,
        )
        try:
            with self._store.transaction() as transaction:
                if self._write_guard is not None:
                    self._write_guard()
                _validate_slate_provenance(transaction, assessment)
                existing = transaction.execute(
                    """SELECT assessment_digest, assessment_json, contract_version,
                              schema_version, active_scope_id, active_scope_digest, season,
                              window_contract_id, window_version, window_id, window_digest,
                              start_utc, end_utc, schedule_state
                       FROM slate_fixture_coverage_assessments WHERE assessment_digest = ?""",
                    (assessment.digest,),
                ).fetchone()
                if existing is not None:
                    if tuple(existing) != values:
                        raise SlateFixtureCoverageIntegrityError(
                            "Stored slate F01 identity differs from its immutable payload."
                        )
                    return assessment.digest
                transaction.execute(
                    """INSERT INTO slate_fixture_coverage_assessments (
                           assessment_digest, assessment_json, contract_version, schema_version,
                           active_scope_id, active_scope_digest, season, window_contract_id,
                           window_version, window_id, window_digest, start_utc, end_utc,
                           schedule_state, first_persisted_at_utc
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, datetime.now(UTC).isoformat(timespec="microseconds")),
                )
                if self._write_guard is not None:
                    self._write_guard()
        except sqlite3.IntegrityError as error:
            raise SlateFixtureCoverageIntegrityError(
                "Slate F01 violates an immutable persistence constraint."
            ) from error
        return assessment.digest

    def get(self, digest: str) -> SlateFixtureCoverageAssessment | None:
        """Read one exact assessment and validate payload plus indexed metadata."""
        if _DIGEST.fullmatch(digest) is None:
            raise ValueError("Slate F01 digest must be a sha256 digest.")
        row = (
            self._store._connection_for_repository()
            .execute(
                """SELECT assessment_json, contract_version, schema_version, active_scope_id,
                      active_scope_digest, season, window_contract_id, window_version,
                      window_id, window_digest, start_utc, end_utc, schedule_state
               FROM slate_fixture_coverage_assessments WHERE assessment_digest = ?""",
                (digest,),
            )
            .fetchone()
        )
        if row is None:
            return None
        try:
            assessment = decode_slate_f01(str(row[0]))
            window = assessment.slate_window
            metadata = (
                assessment.contract_version,
                assessment.schema_version,
                assessment.active_scope.contract_id,
                assessment.active_scope.digest,
                assessment.active_scope.season,
                window.contract_id,
                window.version,
                window.slate_id,
                window.digest,
                window.start_utc,
                window.end_utc,
                assessment.schedule_state.value,
            )
            actual = (
                str(row[1]),
                int(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
                int(row[7]),
                str(row[8]),
                str(row[9]),
                str(row[10]),
                str(row[11]),
                str(row[12]),
            )
            if assessment.digest != digest or metadata != actual:
                raise SlateFixtureCoverageIntegrityError(
                    "Slate F01 row identity differs from its canonical payload."
                )
            _validate_slate_provenance(self._store._connection_for_repository(), assessment)
            return assessment
        except SlateFixtureCoverageIntegrityError:
            raise
        except (TypeError, ValueError, IndexError) as error:
            raise SlateFixtureCoverageIntegrityError("Stored slate F01 is corrupt.") from error


def _validate_slate_provenance(
    connection: sqlite3.Connection | StoreTransaction,
    assessment: SlateFixtureCoverageAssessment,
) -> None:
    """Verify every source, revision, and assertion reference against retained Store rows."""
    scopes = {item.scope.scope_id: item.scope for item in assessment.scope_assessments}
    captures: dict[str, tuple[str, str, ProviderAttemptState]] = {}

    for attempt in assessment.provider_attempts:
        if attempt.capture_id is None:
            if attempt.state is ProviderAttemptState.CAPTURED:
                raise SlateFixtureCoverageIntegrityError(
                    "Captured slate F01 attempt is missing its source capture."
                )
            continue
        if attempt.capture_digest is None:
            raise SlateFixtureCoverageIntegrityError(
                "Slate F01 attempt capture reference is missing its content digest."
            )
        scope = scopes[attempt.scope_id]
        league = league_by_key(scope.league_key)
        expected_source, expected_locator = {
            "openfootball-json": ("openfootball", openfootball_url(league, scope.season)),
            "openfootball-footballtxt": (
                "openfootball-footballtxt",
                openfootball_text_url(league, scope.season),
            ),
        }.get(attempt.provider_id, (None, None))
        row = connection.execute(
            """SELECT c.content_sha256, c.retrieved_at_utc, c.locator, s.source_key
               FROM source_captures AS c
               JOIN source_identities AS s ON s.source_id = c.source_id
               WHERE c.capture_id = ?""",
            (attempt.capture_id,),
        ).fetchone()
        if (
            row is None
            or expected_source is None
            or str(row[0]) != attempt.capture_digest.removeprefix("sha256:")
            or _utc_instant(str(row[1])) != _utc_instant(attempt.retrieved_at_utc)
            or str(row[2]) != expected_locator
            or str(row[3]) != expected_source
        ):
            raise SlateFixtureCoverageIntegrityError(
                f"Slate F01 capture {attempt.capture_id} is missing or has conflicting "
                "source provenance."
            )
        captures[attempt.capture_id] = (attempt.scope_id, attempt.capture_digest, attempt.state)

    for evidence in assessment.coverage_evidence:
        matching_attempt = next(
            (
                item
                for item in assessment.provider_attempts
                if item.attempt_id == evidence.attempt_id
            ),
            None,
        )
        retained = captures.get(evidence.capture_id)
        if (
            matching_attempt is None
            or matching_attempt.state is not ProviderAttemptState.CAPTURED
            or matching_attempt.scope_id != evidence.scope_id
            or matching_attempt.capture_id != evidence.capture_id
            or matching_attempt.capture_digest != evidence.capture_digest
            or retained is None
            or retained[:2] != (evidence.scope_id, evidence.capture_digest)
            or retained[2] is not ProviderAttemptState.CAPTURED
        ):
            raise SlateFixtureCoverageIntegrityError(
                "Slate F01 coverage evidence does not match retained source provenance."
            )

    for revision in assessment.fixture_revisions:
        row = connection.execute(
            "SELECT fixture_id, revision_digest FROM fixture_revisions WHERE revision_id = ?",
            (revision.revision_id,),
        ).fetchone()
        if (
            row is None
            or str(row[0]) != revision.fixture_id
            or str(row[1]) != revision.revision_digest.removeprefix("sha256:")
            or not revision.source_capture_ids
            or any(
                captures.get(capture_id, (None, None, None))[0] != revision.scope_id
                or captures[capture_id][2] is not ProviderAttemptState.CAPTURED
                for capture_id in revision.source_capture_ids
            )
        ):
            raise SlateFixtureCoverageIntegrityError(
                f"Slate F01 fixture revision {revision.revision_id} has invalid source provenance."
            )
        _validate_assertion_links(
            connection,
            revision.source_assertion_ids,
            revision.source_capture_ids,
            revision.revision_id,
        )

    for identity in assessment.identity_resolutions:
        if not identity.source_capture_ids or any(
            captures.get(capture_id, (None, None, None))[0] != identity.scope_id
            or captures[capture_id][2] is not ProviderAttemptState.CAPTURED
            for capture_id in identity.source_capture_ids
        ):
            raise SlateFixtureCoverageIntegrityError(
                f"Slate F01 candidate {identity.candidate_id} has invalid "
                "source capture provenance."
            )
        _validate_assertion_links(
            connection,
            identity.source_assertion_ids,
            identity.source_capture_ids,
            None,
        )


def _validate_assertion_links(
    connection: sqlite3.Connection | StoreTransaction,
    assertion_ids: tuple[str, ...],
    capture_ids: tuple[str, ...],
    revision_id: str | None,
) -> None:
    for assertion_id in assertion_ids:
        row = connection.execute(
            "SELECT capture_id FROM source_assertions WHERE assertion_id = ?", (assertion_id,)
        ).fetchone()
        if row is None or str(row[0]) not in capture_ids:
            raise SlateFixtureCoverageIntegrityError(
                f"Slate F01 source assertion {assertion_id} is missing or has an unrelated capture."
            )
        if (
            revision_id is not None
            and connection.execute(
                """SELECT 1 FROM fixture_revision_assertions
               WHERE revision_id = ? AND assertion_id = ?""",
                (revision_id, assertion_id),
            ).fetchone()
            is None
        ):
            raise SlateFixtureCoverageIntegrityError(
                f"Slate F01 source assertion {assertion_id} is not linked to its fixture revision."
            )


def _utc_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SlateFixtureCoverageIntegrityError(
            "Slate F01 source retrieval time is invalid."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SlateFixtureCoverageIntegrityError(
            "Slate F01 source retrieval time must include a UTC offset."
        )
    return parsed.astimezone(UTC)

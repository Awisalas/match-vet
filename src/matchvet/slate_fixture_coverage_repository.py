"""Immutable F01 persistence for the five-league interval successor."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from matchvet.slate_fixture_coverage import (
    SlateFixtureCoverageAssessment,
    decode_slate_f01,
    encode_slate_f01,
)
from matchvet.store import Store

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
            return assessment
        except SlateFixtureCoverageIntegrityError:
            raise
        except (TypeError, ValueError, IndexError) as error:
            raise SlateFixtureCoverageIntegrityError("Stored slate F01 is corrupt.") from error

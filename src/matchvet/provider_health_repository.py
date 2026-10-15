"""Immutable persistence for fixture and approved contextual Provider Health Records."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

from matchvet.fixture_coverage import (
    SupportedFixtureCoverageAssessment,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.provider_health import (
    F01FixtureScopeReference,
    FixtureCoverageAssessmentReference,
    ProviderAttemptReference,
    ProviderCoverageEvidenceReference,
    ProviderHealthRecord,
    ProviderHealthRecordV2,
    SlateF01FixtureScopeReference,
    SourceCaptureReference,
    provider_health_record_from_canonical_json,
    provider_health_record_to_canonical_json,
    provider_health_v2_record_from_canonical_json,
)
from matchvet.slate_fixture_coverage import SlateFixtureCoverageAssessment
from matchvet.store import Store

_HEALTH_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_F01_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ProviderHealthIntegrityError(ValueError):
    """Stored or proposed F05 data conflicts with its immutable references."""

    code = "MV-F05-HEALTH-INTEGRITY"


class ProviderHealthPersistenceError(RuntimeError):
    """The complete F05 batch could not be committed."""

    code = "MV-F05-PERSISTENCE-FAILED"


@dataclass(frozen=True)
class ProviderHealthInspection:
    assessment_digest: str
    records: tuple[ProviderHealthRecord, ...]
    missing_attempt_ids: tuple[str, ...]


@dataclass(frozen=True)
class _RecordMetadata:
    record_digest: str
    record_json: str
    contract_version: str
    schema_version: int
    provider_id: str
    capability_id: str
    fixture_scope_id: str
    season: str
    matchweek_friday: str
    intended_use_id: str
    checked_at_utc: str
    attempt_id: str
    assessment_digest: str

    def indexed_values(self) -> tuple[object, ...]:
        return (
            self.record_digest,
            self.record_json,
            self.contract_version,
            self.schema_version,
            self.provider_id,
            self.capability_id,
            self.fixture_scope_id,
            self.season,
            self.matchweek_friday,
            self.intended_use_id,
            self.checked_at_utc,
            self.attempt_id,
            self.assessment_digest,
        )


@dataclass(frozen=True)
class _ContextualRecordMetadata:
    record_digest: str
    record_json: str
    contract_version: str
    schema_version: int
    provider_id: str
    capability_id: str
    requested_scope_id: str
    intended_use_id: str
    checked_at_utc: str

    def indexed_values(self) -> tuple[object, ...]:
        return (
            self.record_digest,
            self.record_json,
            self.contract_version,
            self.schema_version,
            self.provider_id,
            self.capability_id,
            self.requested_scope_id,
            self.intended_use_id,
            self.checked_at_utc,
        )


@dataclass(frozen=True)
class _SlateRecordMetadata:
    record_digest: str
    record_json: str
    provider_id: str
    capability_id: str
    scope_id: str
    season: str
    active_scope_digest: str
    window_id: str
    window_digest: str
    start_utc: str
    end_utc: str
    intended_use_id: str
    checked_at_utc: str
    attempt_id: str
    assessment_digest: str

    def indexed_values(self) -> tuple[object, ...]:
        return (
            self.record_digest,
            self.record_json,
            "provider-health-v2",
            2,
            self.provider_id,
            self.capability_id,
            self.scope_id,
            self.season,
            self.active_scope_digest,
            self.window_id,
            self.window_digest,
            self.start_utc,
            self.end_utc,
            self.intended_use_id,
            self.checked_at_utc,
            self.attempt_id,
            self.assessment_digest,
        )


class ProviderHealthRepository:
    """Persist, load, and list immutable F04 values in the authoritative store."""

    def __init__(self, store: Store, *, write_guard: Callable[[], object] | None = None) -> None:
        self._store = store
        self._write_guard = write_guard

    def persist_many(self, records: tuple[ProviderHealthRecord, ...]) -> tuple[str, ...]:
        """Atomically append fixture or contextual observations after exact validation."""
        if not isinstance(records, tuple):
            records = tuple(records)
        if any(isinstance(record, ProviderHealthRecordV2) for record in records):
            if not all(isinstance(record, ProviderHealthRecordV2) for record in records):
                raise ProviderHealthIntegrityError(
                    "One F05 batch must use one exact Provider Health version."
                )
            return self._persist_slate_many(
                tuple(cast(ProviderHealthRecordV2, record) for record in records)
            )
        if self._write_guard is not None:
            self._write_guard()
        if not isinstance(records, tuple):
            records = tuple(records)
        metadata_by_digest: dict[str, _RecordMetadata] = {}
        contextual_metadata: dict[str, _ContextualRecordMetadata] = {}
        records_by_digest: dict[str, ProviderHealthRecord] = {}
        logical_keys: dict[tuple[str, str], str] = {}
        assessments: dict[str, SupportedFixtureCoverageAssessment] = {}

        for record in records:
            if not isinstance(record, ProviderHealthRecord):
                raise TypeError("F05 can persist only typed ProviderHealthRecord values.")
            if record.requested_scope.fixture_scope is None:
                contextual_metadata[record.digest] = _contextual_record_metadata(record)
                records_by_digest[record.digest] = record
                continue
            metadata = _record_metadata(record)
            prior = metadata_by_digest.get(record.digest)
            if prior is not None and prior != metadata:
                raise ProviderHealthIntegrityError(
                    "One F04 digest identifies conflicting canonical records."
                )
            key = (metadata.assessment_digest, metadata.attempt_id)
            prior_digest = logical_keys.get(key)
            if prior_digest is not None and prior_digest != record.digest:
                raise ProviderHealthIntegrityError(
                    "One provider health observation key has conflicting F04 content."
                )
            logical_keys[key] = record.digest
            metadata_by_digest[record.digest] = metadata
            records_by_digest[record.digest] = record

            if metadata.assessment_digest not in assessments:
                assessment = FixtureCoverageRepository(self._store).get(metadata.assessment_digest)
                if assessment is None:
                    raise ProviderHealthIntegrityError(
                        "F05 record references a missing persisted F03 assessment."
                    )
                assessments[metadata.assessment_digest] = assessment
            _validate_record_references(record, assessments[metadata.assessment_digest])

        ordered_digests = tuple(sorted(records_by_digest))
        if not ordered_digests:
            return ()

        persisted_at: str | None = None
        persisted_digests: set[str] = set()
        try:
            with self._store.transaction() as transaction:
                if self._write_guard is not None:
                    self._write_guard()
                for digest in ordered_digests:
                    if self._store.status.schema_version >= 15:
                        slate_owned = transaction.execute(
                            "SELECT 1 FROM slate_provider_health_records WHERE record_digest = ?",
                            (digest,),
                        ).fetchone()
                        if slate_owned is not None:
                            raise ProviderHealthIntegrityError(
                                "One F04 digest appears in historical and successor health tables."
                            )
                    if digest in contextual_metadata:
                        contextual = contextual_metadata[digest]
                        existing_contextual = self.get(digest)
                        if existing_contextual is not None:
                            if existing_contextual != records_by_digest[digest]:
                                raise ProviderHealthIntegrityError(
                                    "Stored contextual health differs from its exact F04 record."
                                )
                            persisted_digests.add(digest)
                            continue
                        if persisted_at is None:
                            persisted_at = datetime.now(UTC).isoformat(timespec="microseconds")
                        transaction.execute(
                            """
                            INSERT INTO contextual_provider_health_records (
                                record_digest, record_json, contract_version,
                                record_schema_version, provider_id, capability_id,
                                requested_scope_id, intended_use_id, checked_at_utc,
                                first_persisted_at_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (*contextual.indexed_values(), persisted_at),
                        )
                        persisted_digests.add(digest)
                        continue
                    metadata = metadata_by_digest[digest]
                    existing = transaction.execute(
                        """
                        SELECT record_digest, record_json, contract_version,
                               record_schema_version, provider_id, capability_id,
                               fixture_scope_id, season, matchweek_friday, intended_use_id,
                               checked_at_utc, attempt_id, assessment_digest
                        FROM provider_health_records
                        WHERE record_digest = ?
                        """,
                        (digest,),
                    ).fetchone()
                    if existing is not None:
                        if tuple(existing) != metadata.indexed_values():
                            raise ProviderHealthIntegrityError(
                                "Stored values for this F04 digest do not match its record."
                            )
                        persisted_digests.add(digest)
                        continue

                    logical = transaction.execute(
                        """
                        SELECT record_digest, record_json, contract_version,
                               record_schema_version, provider_id, capability_id,
                               fixture_scope_id, season, matchweek_friday, intended_use_id,
                               checked_at_utc, attempt_id, assessment_digest,
                               first_persisted_at_utc
                        FROM provider_health_records
                        WHERE assessment_digest = ? AND attempt_id = ?
                        """,
                        (
                            metadata.assessment_digest,
                            metadata.attempt_id,
                        ),
                    ).fetchone()
                    if logical is not None:
                        self._decode_row(tuple(logical), assessments)
                        raise ProviderHealthIntegrityError(
                            "One provider health observation key has different content for the "
                            "same exact F01 assessment."
                        )

                    if persisted_at is None:
                        persisted_at = datetime.now(UTC).isoformat(timespec="microseconds")

                    transaction.execute(
                        """
                        INSERT INTO provider_health_records (
                            record_digest, record_json, contract_version,
                            record_schema_version, provider_id, capability_id,
                            fixture_scope_id, season, matchweek_friday, intended_use_id,
                            checked_at_utc, attempt_id, assessment_digest,
                            first_persisted_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*metadata.indexed_values(), persisted_at),
                    )
                    persisted_digests.add(digest)
                if self._write_guard is not None:
                    self._write_guard()
        except sqlite3.IntegrityError as error:
            raise ProviderHealthIntegrityError(
                "The provider health batch violates an immutable store constraint."
            ) from error
        if self._write_guard is not None:
            self._write_guard()
        return tuple(sorted(persisted_digests))

    def get(self, record_digest: str) -> ProviderHealthRecord | None:
        """Load and validate one exact F04 digest; never select an implicit latest row."""
        _validate_digest(record_digest)
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT record_digest, record_json, contract_version, record_schema_version,
                   provider_id, capability_id, fixture_scope_id, season, matchweek_friday,
                   intended_use_id, checked_at_utc, attempt_id, assessment_digest,
                   first_persisted_at_utc
            FROM provider_health_records
            WHERE record_digest = ?
            """,
            (record_digest,),
        ).fetchone()
        contextual_row = None
        if self._store.status.schema_version >= 14:
            contextual_row = connection.execute(
                """
                SELECT record_digest, record_json, contract_version, record_schema_version,
                       provider_id, capability_id, requested_scope_id, intended_use_id,
                       checked_at_utc, first_persisted_at_utc
                FROM contextual_provider_health_records WHERE record_digest = ?
                """,
                (record_digest,),
            ).fetchone()
        slate_row = None
        if self._store.status.schema_version >= 15:
            slate_row = connection.execute(
                """SELECT record_digest, record_json, contract_version, schema_version,
                          provider_id, capability_id, scope_id, season, active_scope_digest,
                          window_id, window_digest, start_utc, end_utc, intended_use_id,
                          checked_at_utc, attempt_id, assessment_digest, first_persisted_at_utc
                   FROM slate_provider_health_records WHERE record_digest = ?""",
                (record_digest,),
            ).fetchone()
        if sum(value is not None for value in (row, contextual_row, slate_row)) > 1:
            raise ProviderHealthIntegrityError("One F04 digest appears in both health tables.")
        if row is not None:
            return self._decode_row(tuple(row), {})
        if contextual_row is not None:
            return _decode_contextual_row(tuple(contextual_row))
        return None if slate_row is None else self._decode_slate_row(tuple(slate_row), {})

    def _persist_slate_many(self, records: tuple[ProviderHealthRecordV2, ...]) -> tuple[str, ...]:
        if self._store.status.schema_version < 15:
            raise ProviderHealthPersistenceError(
                "This Store does not support immutable interval health writes."
            )
        if self._write_guard is not None:
            self._write_guard()
        metadata_by_digest: dict[str, _SlateRecordMetadata] = {}
        assessment_cache: dict[str, SlateFixtureCoverageAssessment] = {}
        logical_keys: dict[tuple[str, str], str] = {}
        for record in records:
            metadata = _slate_record_metadata(record)
            previous = metadata_by_digest.get(metadata.record_digest)
            if previous is not None and previous != metadata:
                raise ProviderHealthIntegrityError(
                    "One F04 digest identifies conflicting v2 records."
                )
            key = (metadata.assessment_digest, metadata.attempt_id)
            previous_digest = logical_keys.get(key)
            if previous_digest is not None and previous_digest != metadata.record_digest:
                raise ProviderHealthIntegrityError(
                    "One F05 assessment/attempt key has conflicting v2 content."
                )
            logical_keys[key] = metadata.record_digest
            metadata_by_digest[metadata.record_digest] = metadata
            if metadata.assessment_digest not in assessment_cache:
                assessment = FixtureCoverageRepository(self._store).get_any(
                    metadata.assessment_digest
                )
                if type(assessment) is not SlateFixtureCoverageAssessment:
                    raise ProviderHealthIntegrityError(
                        "F05 v2 requires its exact persisted interval F01 assessment."
                    )
                assessment_cache[metadata.assessment_digest] = assessment
            _validate_slate_record_references(record, assessment_cache[metadata.assessment_digest])
        if not metadata_by_digest:
            return ()

        persisted_at = datetime.now(UTC).isoformat(timespec="microseconds")
        persisted: set[str] = set()
        try:
            with self._store.transaction() as transaction:
                if self._write_guard is not None:
                    self._write_guard()
                for digest, metadata in sorted(metadata_by_digest.items()):
                    duplicate = transaction.execute(
                        """SELECT EXISTS (
                                   SELECT 1 FROM provider_health_records WHERE record_digest = ?
                               ) OR EXISTS (
                                   SELECT 1 FROM contextual_provider_health_records
                                   WHERE record_digest = ?
                               )""",
                        (digest, digest),
                    ).fetchone()
                    if duplicate is not None and bool(duplicate[0]):
                        raise ProviderHealthIntegrityError(
                            "A v2 F04 digest is already owned by a historical health table."
                        )
                    existing = transaction.execute(
                        """SELECT record_digest, record_json, contract_version, schema_version,
                                  provider_id, capability_id, scope_id, season, active_scope_digest,
                                  window_id, window_digest, start_utc, end_utc, intended_use_id,
                                  checked_at_utc, attempt_id, assessment_digest
                           FROM slate_provider_health_records WHERE record_digest = ?""",
                        (digest,),
                    ).fetchone()
                    if existing is not None:
                        if tuple(existing) != metadata.indexed_values():
                            raise ProviderHealthIntegrityError(
                                "Stored v2 health differs from its exact canonical record."
                            )
                        persisted.add(digest)
                        continue
                    logical = transaction.execute(
                        """SELECT record_digest, record_json FROM slate_provider_health_records
                           WHERE assessment_digest = ? AND attempt_id = ?""",
                        (metadata.assessment_digest, metadata.attempt_id),
                    ).fetchone()
                    if logical is not None:
                        raise ProviderHealthIntegrityError(
                            "One assessment/attempt key cannot retain changed F04 content."
                        )
                    values = metadata.indexed_values()
                    transaction.execute(
                        """INSERT INTO slate_provider_health_records (
                               record_digest, record_json, contract_version, schema_version,
                               provider_id, capability_id, scope_id, season, active_scope_digest,
                               window_id, window_digest, start_utc, end_utc, intended_use_id,
                               checked_at_utc, attempt_id, assessment_digest,
                               first_persisted_at_utc
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (*values, persisted_at),
                    )
                    persisted.add(digest)
                if self._write_guard is not None:
                    self._write_guard()
        except sqlite3.IntegrityError as error:
            raise ProviderHealthIntegrityError(
                "The interval provider-health batch violates an immutable Store constraint."
            ) from error
        if self._write_guard is not None:
            self._write_guard()
        return tuple(sorted(persisted))

    def _decode_slate_row(
        self,
        row: tuple[object, ...],
        assessment_cache: dict[str, SlateFixtureCoverageAssessment],
    ) -> ProviderHealthRecordV2:
        if len(row) != 18:
            raise ProviderHealthIntegrityError(
                "Stored interval health row has an unsupported shape."
            )
        try:
            record = provider_health_v2_record_from_canonical_json(str(row[1]))
        except ValueError as error:
            raise ProviderHealthIntegrityError("Stored interval health JSON is invalid.") from error
        metadata = _slate_record_metadata(record)
        if tuple(row[:17]) != metadata.indexed_values():
            raise ProviderHealthIntegrityError(
                "Stored interval health metadata differs from its canonical record."
            )
        if not str(row[17]):
            raise ProviderHealthIntegrityError("Stored interval health has no persistence time.")
        if metadata.assessment_digest not in assessment_cache:
            assessment = FixtureCoverageRepository(self._store).get_any(metadata.assessment_digest)
            if type(assessment) is not SlateFixtureCoverageAssessment:
                raise ProviderHealthIntegrityError("Stored v2 health references missing F01 data.")
            assessment_cache[metadata.assessment_digest] = assessment
        _validate_slate_record_references(record, assessment_cache[metadata.assessment_digest])
        return record

    def list_for_assessment(self, assessment_digest: str) -> tuple[ProviderHealthRecord, ...]:
        """Load only validated F05 records for one exact persisted F01 assessment."""
        assessment = FixtureCoverageRepository(self._store).get_any(assessment_digest)
        if assessment is None:
            raise ProviderHealthIntegrityError(
                "F05 history references a missing exact F01 assessment."
            )
        if type(assessment) is SlateFixtureCoverageAssessment:
            rows = (
                self._store._connection_for_repository()
                .execute(
                    """SELECT record_digest, record_json, contract_version, schema_version,
                          provider_id, capability_id, scope_id, season, active_scope_digest,
                          window_id, window_digest, start_utc, end_utc, intended_use_id,
                          checked_at_utc, attempt_id, assessment_digest,
                          first_persisted_at_utc
                   FROM slate_provider_health_records WHERE assessment_digest = ?
                   ORDER BY scope_id, attempt_id, record_digest""",
                    (assessment_digest,),
                )
                .fetchall()
            )
            slate_records = tuple(
                self._decode_slate_row(tuple(row), {assessment_digest: assessment}) for row in rows
            )
            if any(
                _slate_record_metadata(record).assessment_digest != assessment_digest
                for record in slate_records
            ):
                raise ProviderHealthIntegrityError(
                    "F05 interval history references another F01 assessment."
                )
            return slate_records
        assessment = cast(SupportedFixtureCoverageAssessment, assessment)
        scopes = fixture_scopes_for_matchweek(
            assessment.scope_assessments[0].scope.matchweek_friday,
            season=assessment.scope_assessments[0].scope.season,
        )
        scope_order = {scope.scope_id: index for index, scope in enumerate(scopes)}
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT record_digest, record_json, contract_version, record_schema_version,
                   provider_id, capability_id, fixture_scope_id, season, matchweek_friday,
                   intended_use_id, checked_at_utc, attempt_id, assessment_digest,
                   first_persisted_at_utc
            FROM provider_health_records
            WHERE assessment_digest = ?
            ORDER BY fixture_scope_id, attempt_id, record_digest
            """,
            (assessment_digest,),
        ).fetchall()
        records = tuple(
            self._decode_row(
                tuple(row),
                {assessment_digest: assessment},
            )
            for row in rows
        )
        if any(
            _record_metadata(record).assessment_digest != assessment_digest for record in records
        ):
            raise ProviderHealthIntegrityError(
                "F05 exact assessment history contains a wrong-assessment record."
            )
        return tuple(
            sorted(
                records,
                key=lambda record: (
                    scope_order.get(
                        record.requested_scope.fixture_scope.scope_id
                        if record.requested_scope.fixture_scope is not None
                        else "",
                        len(scope_order),
                    ),
                    _record_metadata(record).attempt_id,
                    record.digest,
                ),
            )
        )

    def inspect_for_assessment(self, assessment_digest: str) -> ProviderHealthInspection:
        """Read exact retained dimensions and report missing per-attempt health records."""
        assessment = FixtureCoverageRepository(self._store).get_any(assessment_digest)
        if assessment is None:
            raise ProviderHealthIntegrityError("F05 inspection requires an exact retained F01.")
        records = self.list_for_assessment(assessment_digest)
        retained_attempt_ids = {
            reference.attempt_id
            for record in records
            for reference in _record_references(record)
            if isinstance(reference, ProviderAttemptReference)
        }
        expected_attempt_ids = {attempt.attempt_id for attempt in assessment.provider_attempts}
        return ProviderHealthInspection(
            assessment_digest=assessment_digest,
            records=records,
            missing_attempt_ids=tuple(sorted(expected_attempt_ids - retained_attempt_ids)),
        )

    def list_for_matchweek(
        self,
        season: str,
        friday: str,
        *,
        provider_id: str | None = None,
        capability_id: str | None = None,
        scope_id: str | None = None,
    ) -> tuple[ProviderHealthRecord, ...]:
        """List exact immutable observations in deterministic Matchweek history order."""
        _validate_matchweek(season, friday)
        for label, value in (
            ("provider ID", provider_id),
            ("capability ID", capability_id),
            ("Fixture Scope ID", scope_id),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"History {label} filter must not be empty.")

        clauses = ["season = ?", "matchweek_friday = ?"]
        parameters: list[object] = [season, friday]
        for column, value in (
            ("provider_id", provider_id),
            ("capability_id", capability_id),
            ("fixture_scope_id", scope_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            f"""
            SELECT record_digest, record_json, contract_version, record_schema_version,
                   provider_id, capability_id, fixture_scope_id, season, matchweek_friday,
                   intended_use_id, checked_at_utc, attempt_id, assessment_digest,
                   first_persisted_at_utc
            FROM provider_health_records
            WHERE {" AND ".join(clauses)}
            ORDER BY checked_at_utc, provider_id, capability_id, fixture_scope_id,
                     intended_use_id, record_digest
            """,
            parameters,
        ).fetchall()
        assessment_cache: dict[str, SupportedFixtureCoverageAssessment] = {}
        return tuple(self._decode_row(tuple(row), assessment_cache) for row in rows)

    def _decode_row(
        self,
        row: tuple[object, ...],
        assessment_cache: dict[str, SupportedFixtureCoverageAssessment],
    ) -> ProviderHealthRecord:
        if len(row) != 14:
            raise ProviderHealthIntegrityError("Stored F05 row has an unsupported shape.")
        digest = str(row[0])
        _validate_digest(digest)
        encoded = str(row[1])
        try:
            record = provider_health_record_from_canonical_json(encoded)
        except ValueError as error:
            raise ProviderHealthIntegrityError(
                "Stored F04 canonical JSON is invalid or has a digest mismatch."
            ) from error
        metadata = _record_metadata(record)
        if tuple(row[:13]) != metadata.indexed_values() or not str(row[13]):
            raise ProviderHealthIntegrityError(
                "Stored F05 indexed metadata does not match its canonical record."
            )
        assessment_digest = metadata.assessment_digest
        if assessment_digest not in assessment_cache:
            assessment = FixtureCoverageRepository(self._store).get(assessment_digest)
            if assessment is None:
                raise ProviderHealthIntegrityError(
                    "Stored F05 record references a missing persisted F03 assessment."
                )
            assessment_cache[assessment_digest] = assessment
        _validate_record_references(record, assessment_cache[assessment_digest])
        return record


def _contextual_record_metadata(record: ProviderHealthRecord) -> _ContextualRecordMetadata:
    encoded = provider_health_record_to_canonical_json(record)
    try:
        restored = provider_health_record_from_canonical_json(encoded)
    except ValueError as error:
        raise ProviderHealthIntegrityError(
            "Contextual F04 record failed canonical validation."
        ) from error
    if restored != record:
        raise ProviderHealthIntegrityError("Contextual F04 digest and canonical value disagree.")
    if (
        record.requested_scope.fixture_scope is not None
        or record.provider.provider_id != "open-meteo"
        or record.capability.capability_id != "weather-forecast"
    ):
        raise ProviderHealthIntegrityError("F09 permits only contextual Open-Meteo weather health.")
    return _ContextualRecordMetadata(
        record.digest,
        encoded,
        record.contract_version,
        record.schema_version,
        record.provider.provider_id,
        record.capability.capability_id,
        record.requested_scope.scope_id,
        record.intended_use_id,
        record.checked_at_utc,
    )


def _decode_contextual_row(row: tuple[object, ...]) -> ProviderHealthRecord:
    if len(row) != 10:
        raise ProviderHealthIntegrityError("Stored contextual health row has an unsupported shape.")
    try:
        record = provider_health_record_from_canonical_json(str(row[1]))
    except ValueError as error:
        raise ProviderHealthIntegrityError("Stored contextual F04 JSON is invalid.") from error
    if row[:9] != _contextual_record_metadata(record).indexed_values() or not str(row[9]):
        raise ProviderHealthIntegrityError(
            "Stored contextual health metadata differs from its record."
        )
    return record


def _record_metadata(record: ProviderHealthRecord) -> _RecordMetadata:
    encoded = provider_health_record_to_canonical_json(record)
    try:
        decoded = provider_health_record_from_canonical_json(encoded)
    except ValueError as error:
        raise ProviderHealthIntegrityError(
            "F04 record failed canonical round-trip validation."
        ) from error
    if decoded != record or _HEALTH_DIGEST_RE.fullmatch(record.digest) is None:
        raise ProviderHealthIntegrityError("F04 digest and canonical value do not agree.")
    fixture_scope = record.requested_scope.fixture_scope
    if not isinstance(fixture_scope, F01FixtureScopeReference):
        raise ProviderHealthIntegrityError("F05 requires the exact F01 Fixture Scope.")
    # F05 retains both identity references in top-level provenance. Migration 12 indexes the
    # same canonical locations when it preserves schema-11 rows and enforces the row key.
    assessment_references = tuple(
        reference
        for reference in record.provenance
        if isinstance(reference, FixtureCoverageAssessmentReference)
    )
    unique_assessment_references = set(assessment_references)
    if len(unique_assessment_references) != 1:
        raise ProviderHealthIntegrityError(
            "F05 requires one exact F01 Fixture Coverage Assessment reference."
        )
    assessment_reference = next(iter(unique_assessment_references))
    if _F01_DIGEST_RE.fullmatch(assessment_reference.assessment_digest) is None:
        raise ProviderHealthIntegrityError("F05 assessment digest is malformed.")
    attempt_ids = {
        reference.attempt_id
        for reference in record.provenance
        if isinstance(reference, ProviderAttemptReference)
    }
    if len(attempt_ids) != 1:
        raise ProviderHealthIntegrityError("F05 record must identify exactly one F01 attempt.")
    return _RecordMetadata(
        record_digest=record.digest,
        record_json=encoded,
        contract_version=record.contract_version,
        schema_version=record.schema_version,
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        fixture_scope_id=fixture_scope.scope_id,
        season=fixture_scope.season,
        matchweek_friday=fixture_scope.matchweek_friday,
        intended_use_id=record.intended_use_id,
        checked_at_utc=record.checked_at_utc,
        attempt_id=next(iter(attempt_ids)),
        assessment_digest=assessment_reference.assessment_digest,
    )


def _slate_record_metadata(record: ProviderHealthRecordV2) -> _SlateRecordMetadata:
    encoded = provider_health_record_to_canonical_json(record)
    try:
        decoded = provider_health_v2_record_from_canonical_json(encoded)
    except ValueError as error:
        raise ProviderHealthIntegrityError(
            "F04 v2 failed canonical round-trip validation."
        ) from error
    if decoded != record or _HEALTH_DIGEST_RE.fullmatch(record.digest) is None:
        raise ProviderHealthIntegrityError("F04 v2 digest and canonical value do not agree.")
    fixture_scope = record.requested_scope.fixture_scope
    if not isinstance(fixture_scope, SlateF01FixtureScopeReference):
        raise ProviderHealthIntegrityError("F05 v2 requires the exact interval F01 scope.")
    assessment_references = {
        reference
        for reference in _record_references(record)
        if isinstance(reference, FixtureCoverageAssessmentReference)
    }
    if len(assessment_references) != 1:
        raise ProviderHealthIntegrityError("F05 v2 requires one exact F01 assessment reference.")
    assessment_reference = next(iter(assessment_references))
    if (
        assessment_reference.contract_version != "fixture-coverage-v5-slate-v1"
        or assessment_reference.schema_version != 5
        or _F01_DIGEST_RE.fullmatch(assessment_reference.assessment_digest) is None
    ):
        raise ProviderHealthIntegrityError("F05 v2 F01 version or digest is unsupported.")
    attempt_ids = {
        reference.attempt_id
        for reference in _record_references(record)
        if isinstance(reference, ProviderAttemptReference)
    }
    if len(attempt_ids) != 1:
        raise ProviderHealthIntegrityError("F05 v2 must identify exactly one F01 attempt.")
    return _SlateRecordMetadata(
        record_digest=record.digest,
        record_json=encoded,
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=fixture_scope.scope_id,
        season=fixture_scope.season,
        active_scope_digest=fixture_scope.active_scope.digest,
        window_id=fixture_scope.slate_window.slate_id,
        window_digest=fixture_scope.slate_window.digest,
        start_utc=fixture_scope.slate_window.start_utc,
        end_utc=fixture_scope.slate_window.end_utc,
        intended_use_id=record.intended_use_id,
        checked_at_utc=record.checked_at_utc,
        attempt_id=next(iter(attempt_ids)),
        assessment_digest=assessment_reference.assessment_digest,
    )


def _validate_slate_record_references(
    record: ProviderHealthRecordV2, assessment: SlateFixtureCoverageAssessment
) -> None:
    fixture_scope = record.requested_scope.fixture_scope
    if not isinstance(fixture_scope, SlateF01FixtureScopeReference):
        raise ProviderHealthIntegrityError("F05 v2 has no typed interval F01 reference.")
    scope_assessments = tuple(
        item
        for item in assessment.scope_assessments
        if item.scope.scope_id == fixture_scope.scope_id
    )
    if len(scope_assessments) != 1:
        raise ProviderHealthIntegrityError("F05 v2 scope is absent from its exact F01 assessment.")
    expected_scope = SlateF01FixtureScopeReference.from_f01(assessment, scope_assessments[0].scope)
    if expected_scope != fixture_scope:
        raise ProviderHealthIntegrityError("F05 v2 scope differs from persisted F01.")
    attempt_references = {
        reference.attempt_id: reference
        for reference in _record_references(record)
        if isinstance(reference, ProviderAttemptReference)
    }
    if len(attempt_references) != 1:
        raise ProviderHealthIntegrityError("F05 v2 must retain exactly one F01 attempt snapshot.")
    attempt_id, attempt_reference = next(iter(attempt_references.items()))
    attempts = tuple(item for item in assessment.provider_attempts if item.attempt_id == attempt_id)
    if len(attempts) != 1 or ProviderAttemptReference.from_f01(attempts[0]) != attempt_reference:
        raise ProviderHealthIntegrityError("F05 v2 attempt snapshot differs from persisted F01.")
    if (
        attempt_reference.scope_id != fixture_scope.scope_id
        or attempt_reference.provider_id != record.provider.provider_id
        or attempt_reference.capability_id != record.capability.capability_id
        or attempt_reference.retrieved_at_utc != record.checked_at_utc
    ):
        raise ProviderHealthIntegrityError("F05 v2 identity differs from its F01 attempt.")
    expected_assessment_reference = FixtureCoverageAssessmentReference.from_slate_f01(
        assessment, fixture_scope
    )
    references = {
        reference
        for reference in _record_references(record)
        if isinstance(reference, FixtureCoverageAssessmentReference)
    }
    if references != {expected_assessment_reference}:
        raise ProviderHealthIntegrityError("F05 v2 assessment snapshot differs from persisted F01.")
    expected_coverage = {
        evidence.evidence_id: ProviderCoverageEvidenceReference.from_f01(
            evidence, attempt_reference
        )
        for evidence in assessment.coverage_evidence
        if evidence.attempt_id == attempt_id
        and evidence.scope_id == fixture_scope.scope_id
        and evidence.provider_competition_key == fixture_scope.league_key
        and evidence.provider_season == fixture_scope.season
        and (evidence.capture_id, evidence.capture_digest)
        == (attempt_reference.capture_id, attempt_reference.capture_digest)
    }
    actual_coverage = {
        reference.evidence_id: reference
        for reference in _record_references(record)
        if isinstance(reference, ProviderCoverageEvidenceReference)
    }
    if actual_coverage != expected_coverage:
        raise ProviderHealthIntegrityError("F05 v2 coverage snapshots differ from persisted F01.")
    from matchvet.provider_health_acquisition import build_slate_provider_health_records

    diagnostics = (
        {attempt_id: "retained acquisition diagnostic"}
        if any(code.value == "ACQUISITION_DIAGNOSTIC" for code in record.failure.reason_codes)
        else None
    )
    expected_record = next(
        value
        for value in build_slate_provider_health_records(
            assessment, attempt_diagnostics=diagnostics
        )
        if any(
            isinstance(reference, ProviderAttemptReference) and reference.attempt_id == attempt_id
            for reference in value.provenance
        )
    )
    if expected_record != record:
        raise ProviderHealthIntegrityError(
            "F05 v2 dimensions or snapshots differ from deterministic adapter mapping."
        )


def _record_references(record: ProviderHealthRecord) -> tuple[object, ...]:
    references: list[object] = list(record.provenance)
    for dimension in (
        record.reachability,
        record.capability_availability,
        record.structural_validity,
        record.freshness,
        record.failure,
    ):
        if dimension.evidence is not None:
            references.extend(dimension.evidence.references)
    if record.coverage.witness is not None:
        references.extend(record.coverage.witness.attempts)
        references.extend(record.coverage.witness.evidence)
    return tuple(references)


def _validate_record_references(
    record: ProviderHealthRecord,
    assessment: SupportedFixtureCoverageAssessment,
) -> None:
    fixture_scope = record.requested_scope.fixture_scope
    if not isinstance(fixture_scope, F01FixtureScopeReference):
        raise ProviderHealthIntegrityError("F05 record has no typed F01 Fixture Scope.")
    matching_scope_assessments = tuple(
        scope_assessment
        for scope_assessment in assessment.scope_assessments
        if scope_assessment.scope.scope_id == fixture_scope.scope_id
    )
    if len(matching_scope_assessments) != 1:
        raise ProviderHealthIntegrityError("F05 record scope is absent from persisted F03.")
    scope = matching_scope_assessments[0].scope
    if F01FixtureScopeReference.from_f01(scope) != fixture_scope:
        raise ProviderHealthIntegrityError("F05 record scope differs from persisted F03.")

    attempt_references = {
        reference.attempt_id: reference
        for reference in _record_references(record)
        if isinstance(reference, ProviderAttemptReference)
    }
    if len(attempt_references) != 1:
        raise ProviderHealthIntegrityError("F05 record must identify exactly one F01 attempt.")
    attempt_id, attempt_reference = next(iter(attempt_references.items()))
    matching_attempts = tuple(
        attempt for attempt in assessment.provider_attempts if attempt.attempt_id == attempt_id
    )
    if len(matching_attempts) != 1:
        raise ProviderHealthIntegrityError("F05 attempt is absent from persisted F03.")
    expected_attempt = ProviderAttemptReference.from_f01(matching_attempts[0])
    if attempt_reference != expected_attempt:
        raise ProviderHealthIntegrityError("F05 attempt snapshot differs from persisted F03.")
    if (
        attempt_reference.provider_id != record.provider.provider_id
        or attempt_reference.capability_id != record.capability.capability_id
        or attempt_reference.scope_id != fixture_scope.scope_id
        or attempt_reference.retrieved_at_utc != record.checked_at_utc
        or record.capability.capability_id != "scheduled-fixtures"
    ):
        raise ProviderHealthIntegrityError("F05 record identity differs from its F01 attempt.")

    expected_assessment_reference = FixtureCoverageAssessmentReference.from_f01(
        assessment, fixture_scope
    )
    assessment_references = {
        reference
        for reference in _record_references(record)
        if isinstance(reference, FixtureCoverageAssessmentReference)
    }
    if assessment_references != {expected_assessment_reference}:
        raise ProviderHealthIntegrityError(
            "F05 assessment snapshot differs from the exact persisted F03 scope."
        )

    expected_coverage_references: dict[str, ProviderCoverageEvidenceReference] = {}
    for evidence in assessment.coverage_evidence:
        if (
            evidence.attempt_id == attempt_id
            and evidence.scope_id == attempt_reference.scope_id
            and evidence.provider_competition_key == fixture_scope.league_key
            and evidence.provider_season == fixture_scope.season
            and (evidence.capture_id, evidence.capture_digest)
            == (attempt_reference.capture_id, attempt_reference.capture_digest)
        ):
            expected = ProviderCoverageEvidenceReference.from_f01(evidence, attempt_reference)
            expected_coverage_references[expected.evidence_id] = expected
    coverage_references = {
        reference.evidence_id: reference
        for reference in _record_references(record)
        if isinstance(reference, ProviderCoverageEvidenceReference)
    }
    if coverage_references != expected_coverage_references:
        raise ProviderHealthIntegrityError(
            "F05 coverage evidence differs from the matching persisted F01 evidence."
        )
    for reference in _record_references(record):
        if isinstance(reference, SourceCaptureReference) and (
            reference.capture_id,
            reference.capture_digest,
        ) != (attempt_reference.capture_id, attempt_reference.capture_digest):
            raise ProviderHealthIntegrityError(
                "F05 capture reference differs from its F01 attempt."
            )

    from matchvet.provider_health_acquisition import build_provider_health_records

    diagnostics = (
        {attempt_id: "persisted acquisition diagnostic"}
        if any(code.value == "ACQUISITION_DIAGNOSTIC" for code in record.failure.reason_codes)
        else None
    )
    expected_records = build_provider_health_records(assessment, attempt_diagnostics=diagnostics)
    expected_record = next(
        (
            candidate
            for candidate in expected_records
            if any(
                isinstance(reference, ProviderAttemptReference)
                and reference.attempt_id == attempt_id
                for reference in candidate.provenance
            )
        ),
        None,
    )
    if expected_record != record:
        raise ProviderHealthIntegrityError(
            "F05 record dimensions or references do not match the persisted F01 observation."
        )


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or _HEALTH_DIGEST_RE.fullmatch(value) is None:
        raise ValueError("Provider Health record digest must be a sha256 digest.")


def _validate_matchweek(season: str, friday: str) -> None:
    if not season.strip():
        raise ValueError("Matchweek season must not be empty.")
    try:
        parsed = date.fromisoformat(friday)
    except ValueError as error:
        raise ValueError("Matchweek Friday must use YYYY-MM-DD.") from error
    if parsed.isoformat() != friday or parsed.weekday() != 4:
        raise ValueError("Matchweek history date must be a canonical Friday.")

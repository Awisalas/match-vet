"""Immutable persistence for F05 Provider Health Records."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from matchvet.fixture_coverage import FixtureCoverageAssessment
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.provider_health import (
    EvidenceReferenceKind,
    F01FixtureScopeReference,
    FixtureCoverageAssessmentReference,
    ProviderAttemptReference,
    ProviderCoverageEvidenceReference,
    ProviderHealthRecord,
    SourceCaptureReference,
    provider_health_record_from_canonical_json,
    provider_health_record_to_canonical_json,
)
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
            self.assessment_digest,
        )


class ProviderHealthRepository:
    """Persist, load, and list immutable F04 values in the authoritative store."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def persist_many(self, records: tuple[ProviderHealthRecord, ...]) -> tuple[str, ...]:
        """Atomically append a batch after validating its exact persisted F03 references."""
        if not isinstance(records, tuple):
            records = tuple(records)
        metadata_by_digest: dict[str, _RecordMetadata] = {}
        records_by_digest: dict[str, ProviderHealthRecord] = {}
        logical_keys: dict[tuple[str, str, str, str, str], str] = {}
        assessments: dict[str, FixtureCoverageAssessment] = {}

        for record in records:
            if not isinstance(record, ProviderHealthRecord):
                raise TypeError("F05 can persist only typed ProviderHealthRecord values.")
            metadata = _record_metadata(record)
            prior = metadata_by_digest.get(record.digest)
            if prior is not None and prior != metadata:
                raise ProviderHealthIntegrityError(
                    "One F04 digest identifies conflicting canonical records."
                )
            key = (
                metadata.provider_id,
                metadata.capability_id,
                metadata.fixture_scope_id,
                metadata.intended_use_id,
                metadata.checked_at_utc,
            )
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
                for digest in ordered_digests:
                    metadata = metadata_by_digest[digest]
                    existing = transaction.execute(
                        """
                        SELECT record_digest, record_json, contract_version,
                               record_schema_version, provider_id, capability_id,
                               fixture_scope_id, season, matchweek_friday, intended_use_id,
                               checked_at_utc, assessment_digest
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
                               checked_at_utc, assessment_digest, first_persisted_at_utc
                        FROM provider_health_records
                        WHERE provider_id = ? AND capability_id = ?
                          AND fixture_scope_id = ? AND intended_use_id = ?
                          AND checked_at_utc = ?
                        """,
                        (
                            metadata.provider_id,
                            metadata.capability_id,
                            metadata.fixture_scope_id,
                            metadata.intended_use_id,
                            metadata.checked_at_utc,
                        ),
                    ).fetchone()
                    if logical is not None:
                        prior_record = self._decode_row(tuple(logical), assessments)
                        candidate = records_by_digest[digest]
                        # A cached F01 attempt can recur inside a newer assessment when a
                        # sibling feed was retried. Keep its first exact F03 reference when
                        # every other F04 observation fact still matches.
                        if not _is_replayed_attempt(prior_record, candidate):
                            raise ProviderHealthIntegrityError(
                                "One provider health observation key already has different content."
                            )
                        persisted_digests.add(prior_record.digest)
                        continue

                    if persisted_at is None:
                        persisted_at = datetime.now(UTC).isoformat(timespec="microseconds")

                    transaction.execute(
                        """
                        INSERT INTO provider_health_records (
                            record_digest, record_json, contract_version,
                            record_schema_version, provider_id, capability_id,
                            fixture_scope_id, season, matchweek_friday, intended_use_id,
                            checked_at_utc, assessment_digest, first_persisted_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*metadata.indexed_values(), persisted_at),
                    )
                    persisted_digests.add(digest)
        except sqlite3.IntegrityError as error:
            raise ProviderHealthIntegrityError(
                "The provider health batch violates an immutable store constraint."
            ) from error
        return tuple(sorted(persisted_digests))

    def get(self, record_digest: str) -> ProviderHealthRecord | None:
        """Load and validate one exact F04 digest; never select an implicit latest row."""
        _validate_digest(record_digest)
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT record_digest, record_json, contract_version, record_schema_version,
                   provider_id, capability_id, fixture_scope_id, season, matchweek_friday,
                   intended_use_id, checked_at_utc, assessment_digest,
                   first_persisted_at_utc
            FROM provider_health_records
            WHERE record_digest = ?
            """,
            (record_digest,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_row(tuple(row), {})

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
                   intended_use_id, checked_at_utc, assessment_digest,
                   first_persisted_at_utc
            FROM provider_health_records
            WHERE {" AND ".join(clauses)}
            ORDER BY checked_at_utc, provider_id, capability_id, fixture_scope_id,
                     intended_use_id, record_digest
            """,
            parameters,
        ).fetchall()
        assessment_cache: dict[str, FixtureCoverageAssessment] = {}
        return tuple(self._decode_row(tuple(row), assessment_cache) for row in rows)

    def _decode_row(
        self,
        row: tuple[object, ...],
        assessment_cache: dict[str, FixtureCoverageAssessment],
    ) -> ProviderHealthRecord:
        if len(row) != 13:
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
        if tuple(row[:12]) != metadata.indexed_values() or not str(row[12]):
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
    if fixture_scope is None:
        raise ProviderHealthIntegrityError("F05 requires the exact F01 Fixture Scope.")
    assessment_references = tuple(
        reference
        for reference in _record_references(record)
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
        assessment_digest=assessment_reference.assessment_digest,
    )


def _is_replayed_attempt(persisted: ProviderHealthRecord, candidate: ProviderHealthRecord) -> bool:
    persisted_attempts = tuple(
        reference
        for reference in persisted.provenance
        if isinstance(reference, ProviderAttemptReference)
    )
    candidate_attempts = tuple(
        reference
        for reference in candidate.provenance
        if isinstance(reference, ProviderAttemptReference)
    )
    if len(persisted_attempts) != 1 or persisted_attempts != candidate_attempts:
        return False
    return _without_assessment_reference(persisted) == _without_assessment_reference(candidate)


def _without_assessment_reference(record: ProviderHealthRecord) -> object:
    payload = json.loads(provider_health_record_to_canonical_json(record))
    assessment_kind = EvidenceReferenceKind.FIXTURE_COVERAGE_ASSESSMENT.value
    if isinstance(payload, dict):
        payload["digest"] = "<observation-digest>"

    def normalize(value: object) -> object:
        if isinstance(value, dict):
            if value.get("reference_kind") == assessment_kind:
                return {"reference_kind": assessment_kind}
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(payload)


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
    assessment: FixtureCoverageAssessment,
) -> None:
    fixture_scope = record.requested_scope.fixture_scope
    if fixture_scope is None:
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

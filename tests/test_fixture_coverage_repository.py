from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from matchvet.fixture_coverage import (
    CoverageBasis,
    CoverageBasisKind,
    CoverageBounds,
    CoverageFreshnessResult,
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    ScopeCoverageState,
    assess_fixture_coverage,
    fixture_coverage_assessment_from_canonical_json,
    fixture_coverage_assessment_to_canonical_json,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import (
    FixtureCoverageIntegrityError,
    FixtureCoverageRepository,
)
from matchvet.ingestion import (
    TARGET_LEAGUES,
    FixtureHistoryImporter,
    OpenFootballJSONParser,
    ParsedDataset,
    ParsedRow,
    SourceCaptureInput,
    SourceKind,
    TeamIdentityPolicy,
)
from matchvet.store import MIGRATIONS, InspectionStatus, Store, inspect_store, open_store


def _unknown_assessment() -> FixtureCoverageAssessment:
    return assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-09-25", season="2026-27"),
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )


def _all_state_assessment(store: Store, private_root: Path) -> FixtureCoverageAssessment:
    importer = FixtureHistoryImporter(store, private_root=private_root)
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
    captures: dict[str, tuple[str, str]] = {}
    revision: FixtureRevisionReference | None = None
    unresolved_assertions: tuple[str, ...] = ()

    for index, league in enumerate(TARGET_LEAGUES):
        scope = scopes[index]
        content = f"capture:{league.key}".encode()
        if league.key == "premier_league":
            content = (
                b'{"matches":[{"date":"2026-09-25","time":"20:00",'
                b'"team1":"Arsenal","team2":"Coventry","score":{}}]}'
            )
            dataset = OpenFootballJSONParser().parse(content, league=league, season="2026-27")
            imported = importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url="https://example.test/premier.json",
                    retrieved_at_utc="2026-09-16T12:00:00+00:00",
                    observed_terms="CC0",
                    cache_key="repository-test-premier",
                ),
            )
            observation = importer.observations_for_capture(imported.source_capture_id)[0]
            assert observation.fixture_id is not None
            assert observation.revision_id is not None
            assert observation.revision_digest is not None
            revision = FixtureRevisionReference(
                scope_id=scope.scope_id,
                fixture_id=observation.fixture_id,
                revision_id=observation.revision_id,
                revision_digest=observation.revision_digest,
                source_capture_ids=(imported.source_capture_id,),
                source_assertion_ids=observation.source_assertion_ids,
            )
            captures[scope.scope_id] = (imported.source_capture_id, imported.source_digest)
        elif league.key == "belgian_pro_league":
            dataset = ParsedDataset(
                SourceKind.OPENFOOTBALL,
                league,
                "2026-27",
                (
                    ParsedRow(
                        source_row_key="match-1",
                        home_team="Unknown Brussels",
                        away_team="Unmapped Antwerp",
                        kickoff_utc=datetime(2026, 9, 25, 19, tzinfo=UTC),
                        kickoff_local_date=None,
                        kickoff_local_text="2026-09-25 20:00",
                        kickoff_precision="MINUTE",
                        fields=MappingProxyType({}),
                        raw_fields=MappingProxyType({}),
                    ),
                ),
                "repository-test-unresolved",
            )
            imported = importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url="https://example.test/belgium.json",
                    retrieved_at_utc="2026-09-16T12:06:00+00:00",
                    observed_terms="CC0",
                    cache_key="repository-test-belgium",
                ),
                identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
            )
            observation = importer.observations_for_capture(imported.source_capture_id)[0]
            assert observation.fixture_id is None
            unresolved_assertions = observation.source_assertion_ids
            captures[scope.scope_id] = (imported.source_capture_id, imported.source_digest)
        elif league.key == "ligue_1":
            retained = importer.retain_capture(
                source_kind=SourceKind.OPENFOOTBALL,
                league=league,
                season="2026-27",
                content=b"malformed schedule bytes",
                capture=SourceCaptureInput(
                    source_url="https://example.test/ligue1.json",
                    retrieved_at_utc="2026-09-16T12:04:00+00:00",
                    observed_terms="CC0",
                    cache_key="repository-test-malformed",
                ),
            )
            captures[scope.scope_id] = (retained.capture_id, retained.content_sha256)
        else:
            retained = importer.retain_capture(
                source_kind=SourceKind.OPENFOOTBALL,
                league=league,
                season="2026-27",
                content=content,
                capture=SourceCaptureInput(
                    source_url=f"https://example.test/{league.key}.json",
                    retrieved_at_utc=f"2026-09-16T12:0{index}:00+00:00",
                    observed_terms="CC0",
                    cache_key=f"repository-test-{league.key}",
                ),
            )
            captures[scope.scope_id] = (retained.capture_id, retained.content_sha256)

    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-{index}",
            scope_id=scope.scope_id,
            provider_id="test-provider",
            capability_id="scheduled-fixtures",
            state=(
                ProviderAttemptState.MALFORMED
                if index == 4
                else ProviderAttemptState.CAPTURED
                if index != 5
                else ProviderAttemptState.UNAVAILABLE
            ),
            retrieved_at_utc=f"2026-09-16T12:0{index}:00.000000+00:00",
            http_status=503 if index == 5 else 200,
            capture_id=None if index == 5 else captures[scope.scope_id][0],
            capture_digest=None if index == 5 else captures[scope.scope_id][1],
        )
        for index, scope in enumerate(scopes)
    )
    attempts_by_scope = {attempt.scope_id: attempt for attempt in attempts}

    def full_bounds(index: int) -> CoverageBounds:
        scope = scopes[index]
        return CoverageBounds(scope.window_start_utc, scope.window_end_utc)

    basis = CoverageBasis(CoverageBasisKind.VERSIONED_SOURCE_CONTRACT, "schedule-contract", "v1")

    def evidence(
        index: int,
        *,
        bounds: CoverageBounds | None = None,
        affirmatively_empty: bool = False,
        coverage_basis: CoverageBasis | None = basis,
        permitted: bool = True,
    ) -> ProviderCoverageEvidence:
        scope = scopes[index]
        attempt = attempts_by_scope[scope.scope_id]
        return ProviderCoverageEvidence(
            evidence_id=f"evidence-{index}",
            attempt_id=attempt.attempt_id,
            scope_id=scope.scope_id,
            provider_competition_key=scope.league_key,
            provider_season=scope.season,
            capture_id=cast(str, attempt.capture_id),
            capture_digest=cast(str, attempt.capture_digest),
            coverage_basis=coverage_basis,
            bounds=bounds,
            provider_use_policy_id="use-policy-v1" if permitted else None,
            permitted_for_use=permitted,
            required_partition_ids=("partition-a", "partition-b"),
            accounted_partition_ids=("partition-a", "partition-b") if permitted else (),
            pagination_exhausted=permitted,
            affirmatively_empty=affirmatively_empty,
        )

    partial_end = (
        datetime.fromisoformat(scopes[2].window_start_utc)
        + (
            datetime.fromisoformat(scopes[2].window_end_utc)
            - datetime.fromisoformat(scopes[2].window_start_utc)
        )
        / 2
    )
    evidence_values = (
        evidence(0, bounds=full_bounds(0)),
        evidence(1, bounds=full_bounds(1), affirmatively_empty=True),
        evidence(
            2,
            bounds=CoverageBounds(
                scopes[2].window_start_utc,
                partial_end.isoformat(timespec="microseconds"),
            ),
        ),
        evidence(3, bounds=full_bounds(3)),
        evidence(
            6,
            bounds=None,
            coverage_basis=None,
            permitted=False,
        ),
    )
    freshness = tuple(
        CoverageFreshnessResult(
            evidence_id=f"evidence-{index}",
            policy_id="freshness-policy-v1",
            evaluated_at_utc="2026-09-16T13:00:00.000000+00:00",
            is_current=index != 3,
        )
        for index in range(4)
    )
    identities: list[FixtureIdentityResolution] = []
    if revision is not None:
        identities.append(
            FixtureIdentityResolution(
                candidate_id="candidate-resolved",
                scope_id=scopes[0].scope_id,
                state=FixtureIdentityState.RESOLVED,
                canonical_fixture_id=revision.fixture_id,
                revision_ids=(revision.revision_id,),
                source_capture_ids=revision.source_capture_ids,
                source_assertion_ids=revision.source_assertion_ids,
            )
        )
    identities.append(
        FixtureIdentityResolution(
            candidate_id="synthetic-candidate-not-a-v1-row-id",
            scope_id=scopes[6].scope_id,
            state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
            reason_code="TEAM_MAPPING_UNRESOLVED",
            source_capture_ids=(captures[scopes[6].scope_id][0],),
            source_assertion_ids=unresolved_assertions,
        )
    )
    return assess_fixture_coverage(
        scopes=scopes,
        provider_attempts=attempts,
        coverage_evidence=evidence_values,
        fixture_revisions=() if revision is None else (revision,),
        identity_resolutions=tuple(identities),
        freshness_results=freshness,
    )


def _reassess(
    source: FixtureCoverageAssessment,
    *,
    provider_attempts: tuple[ProviderAttempt, ...] | None = None,
    fixture_revisions: tuple[FixtureRevisionReference, ...] | None = None,
    identity_resolutions: tuple[FixtureIdentityResolution, ...] | None = None,
) -> FixtureCoverageAssessment:
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in source.scope_assessments),
        provider_attempts=(
            source.provider_attempts if provider_attempts is None else provider_attempts
        ),
        coverage_evidence=source.coverage_evidence,
        fixture_revisions=(
            source.fixture_revisions if fixture_revisions is None else fixture_revisions
        ),
        identity_resolutions=(
            source.identity_resolutions if identity_resolutions is None else identity_resolutions
        ),
        freshness_results=source.freshness_results,
    )


def test_unknown_assessment_can_be_saved_loaded_and_listed_by_matchweek(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    assessment = _unknown_assessment()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)

        assert repository.persist(assessment) == assessment.digest
        assert repository.get(assessment.digest) == assessment
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == (assessment,)

    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN


def test_rich_assessment_round_trip_preserves_every_f01_state_and_optional_value(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        repository = FixtureCoverageRepository(store)

        repository.persist(assessment)
        loaded = repository.get(assessment.digest)

        assert loaded == assessment
        assert loaded is not None
        assert tuple(item.coverage_state for item in loaded.scope_assessments) == (
            ScopeCoverageState.COMPLETE,
            ScopeCoverageState.CONFIRMED_EMPTY,
            ScopeCoverageState.PARTIAL,
            ScopeCoverageState.STALE,
            ScopeCoverageState.UNKNOWN,
            ScopeCoverageState.UNKNOWN,
            ScopeCoverageState.UNKNOWN,
        )
        assert {item.state for item in loaded.provider_attempts} == set(ProviderAttemptState)
        assert {item.state for item in loaded.identity_resolutions} == set(FixtureIdentityState)
        assert loaded.freshness_policy_id == "freshness-policy-v1"
        assert {item.is_current for item in loaded.freshness_results} == {False, True}
        assert loaded.schedule_state is MatchweekScheduleState.PARTIAL

        optional_evidence = next(
            item for item in loaded.coverage_evidence if item.evidence_id == "evidence-6"
        )
        assert optional_evidence.coverage_basis is None
        assert optional_evidence.bounds is None
        assert optional_evidence.provider_use_policy_id is None
        assert optional_evidence.permitted_for_use is False
        assert optional_evidence.required_partition_ids == ("partition-a", "partition-b")
        assert optional_evidence.accounted_partition_ids == ()
        assert optional_evidence.pagination_exhausted is False
        assert optional_evidence.affirmatively_empty is False
        assert any(
            item.candidate_id == "synthetic-candidate-not-a-v1-row-id"
            for item in loaded.identity_resolutions
        )


def test_same_digest_is_idempotent_and_different_digest_appends_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import matchvet.fixture_coverage_repository as repository_module

    private_root = tmp_path / "private"
    private_root.mkdir()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FixedDateTime:
            return cls(2026, 9, 26, 12, 0, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(repository_module, "datetime", FixedDateTime)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        first = _all_state_assessment(store, private_root)
        second = _unknown_assessment()
        repository = FixtureCoverageRepository(store)

        repository.persist(first)
        connection = store._connection_for_repository()
        persisted_at = connection.execute(
            "SELECT first_persisted_at_utc FROM fixture_coverage_assessments "
            "WHERE assessment_digest = ?",
            (first.digest,),
        ).fetchone()[0]
        repository.persist(first)
        persisted_at_after_repeat = connection.execute(
            "SELECT first_persisted_at_utc FROM fixture_coverage_assessments "
            "WHERE assessment_digest = ?",
            (first.digest,),
        ).fetchone()[0]
        repository.persist(second)

        history = repository.list_for_matchweek("2026-27", "2026-09-25")
        assert persisted_at_after_repeat == persisted_at
        assert len(history) == 2
        assert {item.digest for item in history} == {first.digest, second.digest}
        assert tuple(item.digest for item in history) == tuple(
            sorted((first.digest, second.digest))
        )
        assert repository.get(first.digest) == first
        assert repository.get(second.digest) == second
        assert repository.get("sha256:" + "0" * 64) is None

        assert (
            connection.execute("SELECT count(*) FROM fixture_coverage_assessments").fetchone()[0]
            == 2
        )
        assert connection.execute(
            "SELECT count(*) FROM fixture_coverage_assessment_revisions "
            "WHERE assessment_digest = ?",
            (first.digest,),
        ).fetchone()[0] == len(first.fixture_revisions)


def test_every_f03_table_rejects_updates_and_deletes(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    mutation_columns = {
        "fixture_coverage_assessments": "assessment_json",
        "fixture_coverage_assessment_revisions": "expected_revision_digest",
        "fixture_coverage_assessment_captures": "expected_content_sha256",
        "fixture_coverage_assessment_assertions": "source_capture_id",
    }

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        repository = FixtureCoverageRepository(store)
        repository.persist(assessment)

        for table, column in mutation_columns.items():
            with pytest.raises(sqlite3.IntegrityError), store.transaction() as transaction:
                transaction.execute(
                    f"UPDATE {table} SET {column} = {column} WHERE assessment_digest = ?",
                    (assessment.digest,),
                )
            with pytest.raises(sqlite3.IntegrityError), store.transaction() as transaction:
                transaction.execute(
                    f"DELETE FROM {table} WHERE assessment_digest = ?",
                    (assessment.digest,),
                )


def test_assessment_and_provenance_links_roll_back_as_one_transaction(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        repository = FixtureCoverageRepository(store)
        connection = store._connection_for_repository()
        connection.execute(
            """
            CREATE TEMP TRIGGER fail_fixture_coverage_capture_link
            BEFORE INSERT ON main.fixture_coverage_assessment_captures
            BEGIN
                SELECT RAISE(ABORT, 'injected F03 link failure');
            END
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="injected F03 link failure"):
            repository.persist(assessment)

        connection.execute("DROP TRIGGER temp.fail_fixture_coverage_capture_link")
        assert repository.get(assessment.digest) is None
        assert (
            connection.execute(
                "SELECT count(*) FROM fixture_coverage_assessments WHERE assessment_digest = ?",
                (assessment.digest,),
            ).fetchone()[0]
            == 0
        )
        for table in (
            "fixture_coverage_assessment_revisions",
            "fixture_coverage_assessment_captures",
            "fixture_coverage_assessment_assertions",
        ):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE assessment_digest = ?",
                    (assessment.digest,),
                ).fetchone()[0]
                == 0
            )
        assert connection.execute("SELECT count(*) FROM source_captures").fetchone()[0] > 0
        assert connection.execute("SELECT count(*) FROM fixture_revisions").fetchone()[0] > 0


def test_persist_rejects_missing_or_mismatched_v1_provenance(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        valid = _all_state_assessment(store, private_root)
        repository = FixtureCoverageRepository(store)
        attempts = list(valid.provider_attempts)
        ligue_attempt_index = next(
            index
            for index, attempt in enumerate(attempts)
            if attempt.scope_id.startswith("ligue_1:")
        )
        ligue_attempt = attempts[ligue_attempt_index]
        attempts[ligue_attempt_index] = replace(
            ligue_attempt,
            capture_id="missing-source-capture",
            capture_digest="a" * 64,
        )
        missing_capture = _reassess(valid, provider_attempts=tuple(attempts))

        attempts[ligue_attempt_index] = replace(
            ligue_attempt,
            capture_digest="b" * 64,
        )
        mismatched_capture_digest = _reassess(valid, provider_attempts=tuple(attempts))

        revision = valid.fixture_revisions[0]
        resolved = next(
            identity
            for identity in valid.identity_resolutions
            if identity.state is FixtureIdentityState.RESOLVED
        )
        missing_revision_id = "missing-v1-revision"
        missing_revision = _reassess(
            valid,
            fixture_revisions=(replace(revision, revision_id=missing_revision_id),),
            identity_resolutions=(
                replace(resolved, revision_ids=(missing_revision_id,)),
                *(item for item in valid.identity_resolutions if item is not resolved),
            ),
        )
        mismatched_revision_digest = _reassess(
            valid,
            fixture_revisions=(replace(revision, revision_digest="c" * 64),),
        )
        missing_assertion = _reassess(
            valid,
            fixture_revisions=(replace(revision, source_assertion_ids=("missing-v1-assertion",)),),
        )
        wrong_fixture_id = replace(revision, fixture_id="different-canonical-fixture")
        wrong_resolved_fixture = replace(
            valid,
            fixture_revisions=(wrong_fixture_id,),
            identity_resolutions=tuple(
                replace(item, canonical_fixture_id=wrong_fixture_id.fixture_id)
                if item.state is FixtureIdentityState.RESOLVED
                else item
                for item in valid.identity_resolutions
            ),
            digest="",
        )
        wrong_capture_association = _reassess(
            valid,
            identity_resolutions=tuple(
                replace(
                    item,
                    source_capture_ids=(valid.fixture_revisions[0].source_capture_ids[0],),
                )
                if item.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
                else item
                for item in valid.identity_resolutions
            ),
        )

        invalid_assessments = (
            missing_capture,
            mismatched_capture_digest,
            missing_revision,
            mismatched_revision_digest,
            missing_assertion,
            wrong_resolved_fixture,
            wrong_capture_association,
        )
        for invalid in invalid_assessments:
            with pytest.raises(FixtureCoverageIntegrityError):
                repository.persist(invalid)
            assert repository.get(invalid.digest) is None


@pytest.mark.parametrize("damage", ("digest", "contract", "schema", "canonical"))
def test_loading_rejects_corrupt_or_unsupported_f01_payloads(tmp_path: Path, damage: str) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _unknown_assessment()
        repository = FixtureCoverageRepository(store)
        repository.persist(assessment)
        connection = store._connection_for_repository()
        connection.execute("DROP TRIGGER fixture_coverage_assessments_no_update")
        payload = connection.execute(
            "SELECT assessment_json FROM fixture_coverage_assessments WHERE assessment_digest = ?",
            (assessment.digest,),
        ).fetchone()[0]
        if damage == "canonical":
            damaged_payload = f" {payload}"
        else:
            import json

            value = json.loads(payload)
            if damage == "digest":
                value["schedule_state"] = "PARTIAL"
            elif damage == "contract":
                value["contract_version"] = "fixture-coverage-future"
            else:
                value["schema_version"] = 99
            damaged_payload = json.dumps(
                value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            )
        connection.execute(
            "UPDATE fixture_coverage_assessments SET assessment_json = ? "
            "WHERE assessment_digest = ?",
            (damaged_payload, assessment.digest),
        )

        with pytest.raises(FixtureCoverageIntegrityError):
            repository.get(assessment.digest)


def test_loading_rejects_reordered_normalized_tuple_under_original_digest(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        payload = json.loads(fixture_coverage_assessment_to_canonical_json(assessment))
        payload["coverage_evidence"][0]["required_partition_ids"].reverse()
        reordered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)

        with pytest.raises(FixtureCoveragePayloadError):
            fixture_coverage_assessment_from_canonical_json(reordered)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("revision_id", "missing-v1-revision"),
        ("revision_digest", "f" * 64),
        ("fixture_id", "different-canonical-fixture"),
        ("source_capture_ids", ("missing-source-capture",)),
        ("source_assertion_ids", ("missing-v1-assertion",)),
    ),
)
def test_persist_rejects_scope_revision_projection_that_differs_from_f01_root(
    tmp_path: Path, field: str, value: object
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        first_scope = assessment.scope_assessments[0]
        revision = first_scope.fixture_revisions[0]
        if field == "revision_id":
            corrupted_revision = replace(revision, revision_id=cast(str, value))
        elif field == "revision_digest":
            corrupted_revision = replace(revision, revision_digest=cast(str, value))
        elif field == "fixture_id":
            corrupted_revision = replace(revision, fixture_id=cast(str, value))
        elif field == "source_capture_ids":
            corrupted_revision = replace(revision, source_capture_ids=cast(tuple[str, ...], value))
        else:
            corrupted_revision = replace(
                revision, source_assertion_ids=cast(tuple[str, ...], value)
            )
        corrupted_scope = replace(first_scope, fixture_revisions=(corrupted_revision,))
        corrupted_assessment = replace(
            assessment,
            scope_assessments=(corrupted_scope, *assessment.scope_assessments[1:]),
            digest="",
        )

        with pytest.raises(FixtureCoverageIntegrityError):
            FixtureCoverageRepository(store).persist(corrupted_assessment)


def test_persist_rejects_scope_attempt_projection_that_differs_from_f01_root(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        first_scope = assessment.scope_assessments[0]
        corrupted_scope = replace(first_scope, provider_attempt_ids=())
        corrupted_assessment = replace(
            assessment,
            scope_assessments=(corrupted_scope, *assessment.scope_assessments[1:]),
            digest="",
        )

        with pytest.raises(FixtureCoverageIntegrityError):
            FixtureCoverageRepository(store).persist(corrupted_assessment)


def test_loading_rejects_provenance_link_corruption(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assessment = _all_state_assessment(store, private_root)
        repository = FixtureCoverageRepository(store)
        repository.persist(assessment)
        connection = store._connection_for_repository()
        connection.execute("DROP TRIGGER fixture_coverage_assessment_captures_no_update")
        connection.execute(
            "UPDATE fixture_coverage_assessment_captures "
            "SET expected_content_sha256 = ? WHERE assessment_digest = ?",
            ("d" * 64, assessment.digest),
        )

        with pytest.raises(FixtureCoverageIntegrityError):
            repository.get(assessment.digest)


def test_persist_rejects_unsupported_f01_contract_and_schema_versions(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        assessment = _unknown_assessment()

        for unsupported in (
            replace(assessment, contract_version="future-contract", digest=""),
            replace(assessment, schema_version=99, digest=""),
        ):
            with pytest.raises(FixtureCoverageIntegrityError):
                repository.persist(unsupported)


def test_schema_nine_migrates_existing_v1_and_t05_records_unchanged(tmp_path: Path) -> None:
    from matchvet.matchweek import freeze_matchweek, replay_matchweek

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root, migrations=MIGRATIONS[:9]) as store:
        _all_state_assessment(store, private_root)
        before_importer = FixtureHistoryImporter(store, private_root=private_root)
        before_fixtures = before_importer.fixtures()
        before_captures = before_importer.source_captures()
        before_assertions = before_importer.source_assertions()
        frozen = freeze_matchweek(
            store,
            "2026-09-25",
            as_of_utc="2026-09-20T00:00:00+00:00",
            created_at_utc="2026-09-20T00:00:00+00:00",
        )
        before_artifacts = store.artifact_catalog()
        before_ledger = (
            store._connection_for_repository()
            .execute(
                "SELECT migration_number, name, checksum FROM schema_migrations "
                "ORDER BY migration_number"
            )
            .fetchall()
        )
        assert store.status.schema_version == 9

    with open_store(database_path, private_root=private_root) as migrated:
        after_importer = FixtureHistoryImporter(migrated, private_root=private_root)
        assert migrated.status.schema_version == 10
        assert after_importer.fixtures() == before_fixtures
        assert after_importer.source_captures() == before_captures
        assert after_importer.source_assertions() == before_assertions
        assert migrated.artifact_catalog() == before_artifacts
        assert replay_matchweek(migrated, "2026-09-25").freeze == frozen
        assert inspect_store(database_path, private_root=private_root).status is (
            InspectionStatus.HEALTHY
        )
        connection = migrated._connection_for_repository()
        after_ledger = connection.execute(
            "SELECT migration_number, name, checksum FROM schema_migrations "
            "ORDER BY migration_number"
        ).fetchall()
        assert tuple(tuple(row) for row in after_ledger[:9]) == tuple(
            tuple(row) for row in before_ledger
        )
        assert after_ledger[9][0:3] == (
            10,
            "fixture_coverage_assessment_persistence",
            MIGRATIONS[9].checksum,
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute("SELECT count(*) FROM fixture_coverage_assessments").fetchone()[0]
            == 0
        )
        f03_objects = connection.execute(
            """
            SELECT type, name FROM sqlite_master
            WHERE name LIKE 'fixture_coverage_assessment%'
            ORDER BY type, name
            """
        ).fetchall()
        assert len(f03_objects) >= 13

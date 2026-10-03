from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from matchvet.fixture_coverage import (
    CoverageBasis,
    CoverageBasisKind,
    CoverageBounds,
    CoverageFreshnessResult,
    FixtureCoverageAssessment,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    FixtureScope,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import (
    FixtureCoverageIntegrityError,
    FixtureCoverageRepository,
)
from matchvet.ingestion import (
    TARGET_LEAGUES,
    FixtureCaptureObservation,
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    FootballDataCSVParser,
    IngestionPlan,
    OpenFootballJSONParser,
    SourceCaptureInput,
    SourceKind,
    StaticSourceFetcher,
    deterministic_identifier,
    league_by_key,
    openfootball_url,
)
from matchvet.matchweek_membership import MatchweekMembershipError
from matchvet.operator_fixture_attestation import (
    CandidateComparisonConfirmation,
    OfficialPublicationReference,
    OperatorAttestationOutcome,
    OperatorComparisonConfirmations,
    derive_attested_fixture_coverage,
    make_operator_coverage_attestation,
    policy_publications_for_scope,
)
from matchvet.provider_health import ProviderAttemptReference, ProviderHealthRecord
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import CanonicalIdentifier, Store, open_store


def _assessment(attempts: tuple[ProviderAttempt, ...]) -> FixtureCoverageAssessment:
    return assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-09-25", season="2026-27"),
        provider_attempts=attempts,
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )


def _certification_publications_for_scope(
    scope: FixtureScope,
) -> tuple[OfficialPublicationReference, ...]:
    test_urls = {
        "ligue-1-programmation": (
            "https://ligue1.com/fr/articles/l1_article_90001-programmation-de-la-journee"
        ),
        "liga-portugal-round-updates": (
            "https://www.ligaportugal.pt/news/90001/horarios-da-jornada-da-liga"
        ),
    }
    return tuple(
        replace(item, official_url=test_urls[item.publication_id])
        if item.publication_id in test_urls
        else item
        for item in policy_publications_for_scope(scope)
    )


def test_f05_exact_assessment_read_is_scope_ordered_and_never_substitutes(
    tmp_path: Path,
) -> None:
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
    attempts = (
        ProviderAttempt(
            attempt_id="attempt-z",
            scope_id=scopes[2].scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        ),
        ProviderAttempt(
            attempt_id="attempt-a",
            scope_id=scopes[0].scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        ),
    )
    first = _assessment(attempts)
    other = _assessment((attempts[0],))

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessments = FixtureCoverageRepository(store)
        health = ProviderHealthRepository(store)
        assessments.persist(first)
        assessments.persist(other)
        health.persist_many(build_provider_health_records(first))
        health.persist_many(build_provider_health_records(other))

        exact = health.list_for_assessment(first.digest)

    actual_attempt_ids = tuple(
        next(
            reference.attempt_id
            for reference in record.provenance
            if isinstance(reference, ProviderAttemptReference)
        )
        for record in exact
    )
    assert actual_attempt_ids == ("attempt-a", "attempt-z")
    assert {record.digest for record in exact}.isdisjoint(
        record.digest for record in build_provider_health_records(other)
    )
    assert set(actual_attempt_ids) == {"attempt-a", "attempt-z"}


def _persistable_empty_assessment(
    store: Store,
    tmp_path: Path,
    *,
    coverage_mode: str = "confirmed_empty",
) -> FixtureCoverageAssessment:
    if coverage_mode not in {"confirmed_empty", "partial", "stale"}:
        raise ValueError(f"Unsupported test coverage mode: {coverage_mode}")
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    attempts: list[ProviderAttempt] = []
    evidence: list[ProviderCoverageEvidence] = []
    freshness: list[CoverageFreshnessResult] = []
    for index, (scope, league) in enumerate(zip(scopes, TARGET_LEAGUES, strict=True)):
        capture = importer.retain_capture(
            source_kind=SourceKind.OPENFOOTBALL,
            league=league,
            season=scope.season,
            content=f"empty-schedule-{index}".encode(),
            capture=SourceCaptureInput(
                source_url=f"https://example.test/{league.key}.json",
                retrieved_at_utc="2026-09-16T12:00:00+00:00",
                observed_terms="CC0",
                cache_key=f"f06-empty-{index}",
            ),
        )
        attempt = ProviderAttempt(
            attempt_id=f"attempt-{index}",
            scope_id=scope.scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.CAPTURED,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
            http_status=200,
            capture_id=capture.capture_id,
            capture_digest=capture.content_sha256,
        )
        attempts.append(attempt)
        evidence.append(
            ProviderCoverageEvidence(
                evidence_id=f"evidence-{index}",
                attempt_id=attempt.attempt_id,
                scope_id=scope.scope_id,
                provider_competition_key=scope.league_key,
                provider_season=scope.season,
                capture_id=capture.capture_id,
                capture_digest=capture.content_sha256,
                coverage_basis=CoverageBasis(
                    CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, f"test-metadata-{index}"
                ),
                bounds=CoverageBounds(
                    scope.window_start_utc,
                    (
                        scope.window_end_utc
                        if coverage_mode == "confirmed_empty"
                        else (
                            datetime.fromisoformat(scope.window_start_utc) + timedelta(hours=12)
                        ).isoformat(timespec="microseconds")
                    ),
                ),
                provider_use_policy_id="f06-test-policy-v1",
                permitted_for_use=True,
                pagination_exhausted=True,
                affirmatively_empty=coverage_mode == "confirmed_empty",
            )
        )
        freshness.append(
            CoverageFreshnessResult(
                evidence_id=f"evidence-{index}",
                policy_id="f06-test-freshness-v1",
                evaluated_at_utc="2026-09-16T13:00:00.000000+00:00",
                is_current=coverage_mode != "stale",
            )
        )

    return assess_fixture_coverage(
        scopes=scopes,
        provider_attempts=tuple(attempts),
        coverage_evidence=tuple(evidence),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=tuple(freshness),
    )


def _persistable_schedule_assessment(
    store: Store,
    tmp_path: Path,
    rows: tuple[tuple[str, str, str, str], ...],
    *,
    duplicate_first_candidate: bool = False,
    venue_for_first: str | None = None,
) -> FixtureCoverageAssessment:
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    attempts: list[ProviderAttempt] = []
    evidence: list[ProviderCoverageEvidence] = []
    freshness: list[CoverageFreshnessResult] = []
    revisions: list[FixtureRevisionReference] = []
    identities: list[FixtureIdentityResolution] = []

    for index, (scope, league) in enumerate(zip(scopes, TARGET_LEAGUES, strict=True)):
        observations: tuple[FixtureCaptureObservation, ...] = ()
        if index == 0:
            match_payload = [
                {
                    "date": date_text,
                    "time": time_text,
                    "team1": home,
                    "team2": away,
                    **(
                        {"venue": venue_for_first}
                        if candidate_index == 0 and venue_for_first is not None
                        else {}
                    ),
                    "score": {},
                }
                for candidate_index, (date_text, time_text, home, away) in enumerate(rows)
            ]
            content = json.dumps({"matches": match_payload}, separators=(",", ":")).encode()
            dataset = OpenFootballJSONParser().parse(content, league=league, season=scope.season)
            imported = importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url="https://example.test/premier.json",
                    retrieved_at_utc="2026-09-16T12:00:00+00:00",
                    observed_terms="CC0",
                    cache_key="f06-scheduled-premier",
                ),
            )
            observations = importer.observations_for_capture(imported.source_capture_id)
            capture_id = imported.source_capture_id
            capture_digest = imported.source_digest
        else:
            capture = importer.retain_capture(
                source_kind=SourceKind.OPENFOOTBALL,
                league=league,
                season=scope.season,
                content=f"empty-schedule-{index}".encode(),
                capture=SourceCaptureInput(
                    source_url=f"https://example.test/{league.key}.json",
                    retrieved_at_utc="2026-09-16T12:00:00+00:00",
                    observed_terms="CC0",
                    cache_key=f"f06-scheduled-empty-{index}",
                ),
            )
            capture_id = capture.capture_id
            capture_digest = capture.content_sha256
        attempt = ProviderAttempt(
            attempt_id=f"scheduled-attempt-{index}",
            scope_id=scope.scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.CAPTURED,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
            http_status=200,
            capture_id=capture_id,
            capture_digest=capture_digest,
        )
        attempts.append(attempt)
        is_empty = index > 0
        evidence_id = f"scheduled-evidence-{index}"
        evidence.append(
            ProviderCoverageEvidence(
                evidence_id=evidence_id,
                attempt_id=attempt.attempt_id,
                scope_id=scope.scope_id,
                provider_competition_key=scope.league_key,
                provider_season=scope.season,
                capture_id=capture_id,
                capture_digest=capture_digest,
                coverage_basis=CoverageBasis(
                    CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, f"test-metadata-{index}"
                ),
                bounds=CoverageBounds(scope.window_start_utc, scope.window_end_utc),
                provider_use_policy_id="f06-test-policy-v1",
                permitted_for_use=True,
                pagination_exhausted=True,
                affirmatively_empty=is_empty,
            )
        )
        freshness.append(
            CoverageFreshnessResult(
                evidence_id=evidence_id,
                policy_id="f06-test-freshness-v1",
                evaluated_at_utc="2026-09-16T13:00:00.000000+00:00",
                is_current=True,
            )
        )
        for candidate_index, observation in enumerate(observations):
            assert observation.fixture_id is not None
            assert observation.revision_id is not None
            assert observation.revision_digest is not None
            revisions.append(
                FixtureRevisionReference(
                    scope_id=scope.scope_id,
                    fixture_id=observation.fixture_id,
                    revision_id=observation.revision_id,
                    revision_digest=observation.revision_digest,
                    source_capture_ids=(capture_id,),
                    source_assertion_ids=observation.source_assertion_ids,
                )
            )
            identities.append(
                FixtureIdentityResolution(
                    candidate_id=f"candidate-{candidate_index}",
                    scope_id=scope.scope_id,
                    state=FixtureIdentityState.RESOLVED,
                    canonical_fixture_id=observation.fixture_id,
                    revision_ids=(observation.revision_id,),
                )
            )
            if duplicate_first_candidate and candidate_index == 0:
                identities.append(
                    FixtureIdentityResolution(
                        candidate_id="candidate-duplicate-provider-row",
                        scope_id=scope.scope_id,
                        state=FixtureIdentityState.RESOLVED,
                        canonical_fixture_id=observation.fixture_id,
                        revision_ids=(observation.revision_id,),
                    )
                )

    return assess_fixture_coverage(
        scopes=scopes,
        provider_attempts=tuple(attempts),
        coverage_evidence=tuple(evidence),
        fixture_revisions=tuple(revisions),
        identity_resolutions=tuple(identities),
        freshness_results=tuple(freshness),
    )


def _assessment_with_revision(
    store: Store,
    assessment: FixtureCoverageAssessment,
    *,
    status: str,
    kickoff_state: str | None = None,
    kickoff_utc: str | None = None,
    source_round: str | None = None,
    keep_prior_revision: bool = False,
) -> FixtureCoverageAssessment:
    original = assessment.fixture_revisions[0]
    prior = (
        store._connection_for_repository()
        .execute(
            """
        SELECT kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
               source_round, source_capture_id
        FROM fixture_revisions WHERE revision_id = ?
        """,
            (original.revision_id,),
        )
        .fetchone()
    )
    assert prior is not None
    effective_kickoff_state = kickoff_state or str(prior[0])
    kickoff_overridden = kickoff_state is not None or kickoff_utc is not None
    effective_kickoff_utc = kickoff_utc if kickoff_overridden else prior[1]
    payload = {
        "fixture_status": status,
        "kickoff_local_text": prior[2] if not kickoff_overridden else None,
        "kickoff_precision": (
            str(prior[3])
            if not kickoff_overridden
            else "INSTANT"
            if effective_kickoff_state == "OBSERVED"
            else "UNKNOWN"
        ),
        "kickoff_state": effective_kickoff_state,
        "kickoff_utc": effective_kickoff_utc,
        "source_round": source_round if source_round is not None else prior[4],
    }
    revision_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    revision_id = deterministic_identifier(
        "fixture_revision", f"{original.fixture_id}:{revision_digest}"
    )
    assertion_ids = original.source_assertion_ids
    with store.transaction() as transaction:
        transaction.add_identifier_if_missing(CanonicalIdentifier("fixture_revision", revision_id))
        transaction.execute(
            """
            INSERT INTO fixture_revisions (
                revision_id, fixture_id, predecessor_revision_id, revision_digest,
                kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
                fixture_status, source_round, observed_at_utc, source_capture_id,
                source_assertion_ids_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                original.fixture_id,
                original.revision_id,
                revision_digest,
                payload["kickoff_state"],
                payload["kickoff_utc"],
                payload["kickoff_local_text"],
                payload["kickoff_precision"],
                status,
                payload["source_round"],
                "2026-09-16T13:00:00.000000+00:00",
                str(prior[5]),
                json.dumps(assertion_ids, ensure_ascii=True, separators=(",", ":")),
                "2026-09-16T13:00:00.000000+00:00",
            ),
        )
        for assertion_id in assertion_ids:
            transaction.execute(
                """
                INSERT INTO fixture_revision_assertions (revision_id, assertion_id)
                VALUES (?, ?)
                """,
                (revision_id, assertion_id),
            )

    replacement = FixtureRevisionReference(
        scope_id=original.scope_id,
        fixture_id=original.fixture_id,
        revision_id=revision_id,
        revision_digest=revision_digest,
        source_capture_ids=original.source_capture_ids,
        source_assertion_ids=assertion_ids,
    )
    revision_refs = (
        (*assessment.fixture_revisions, replacement)
        if keep_prior_revision
        else (replacement, *assessment.fixture_revisions[1:])
    )
    prior_identity = assessment.identity_resolutions[0]
    identity_revision_ids = (
        (*prior_identity.revision_ids, revision_id) if keep_prior_revision else (revision_id,)
    )
    identities = (
        replace(prior_identity, revision_ids=identity_revision_ids),
        *assessment.identity_resolutions[1:],
    )
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in assessment.scope_assessments),
        provider_attempts=assessment.provider_attempts,
        coverage_evidence=assessment.coverage_evidence,
        fixture_revisions=revision_refs,
        identity_resolutions=identities,
        freshness_results=assessment.freshness_results,
    )


def _assessment_with_higher_authority_revision(
    store: Store,
    tmp_path: Path,
    assessment: FixtureCoverageAssessment,
    *,
    kickoff: str = "12:00",
    retrieved_at: str = "2026-09-17T12:00:00+00:00",
    cache_key: str = "f06-higher-authority",
    attempt_id: str = "higher-authority-attempt",
    candidate_id: str = "candidate-higher-authority-row",
) -> FixtureCoverageAssessment:
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    content = b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC\n" + (
        f"E0,25/09/2026,{kickoff},Start United,Start City,,,,,,,\n".encode()
    )
    dataset = FootballDataCSVParser().parse(
        content,
        league=league_by_key("premier_league"),
        season="2026-27",
    )
    imported = importer.import_dataset(
        dataset,
        content,
        SourceCaptureInput(
            source_url="https://example.test/football-data.csv",
            retrieved_at_utc=retrieved_at,
            observed_terms="restricted test capture",
            cache_key=cache_key,
        ),
    )
    observations = importer.observations_for_capture(imported.source_capture_id)
    assert len(observations) == 1
    observation = observations[0]
    assert observation.fixture_id == assessment.fixture_revisions[0].fixture_id
    assert observation.revision_id is not None
    assert observation.revision_digest is not None
    scope = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")[0]
    attempt = ProviderAttempt(
        attempt_id=attempt_id,
        scope_id=scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc=datetime.fromisoformat(retrieved_at)
        .astimezone(UTC)
        .isoformat(timespec="microseconds"),
        http_status=200,
        capture_id=imported.source_capture_id,
        capture_digest=imported.source_digest,
    )
    revision = FixtureRevisionReference(
        scope_id=scope.scope_id,
        fixture_id=observation.fixture_id,
        revision_id=observation.revision_id,
        revision_digest=observation.revision_digest,
        source_capture_ids=(imported.source_capture_id,),
        source_assertion_ids=observation.source_assertion_ids,
    )
    identity = FixtureIdentityResolution(
        candidate_id=candidate_id,
        scope_id=scope.scope_id,
        state=FixtureIdentityState.RESOLVED,
        canonical_fixture_id=observation.fixture_id,
        revision_ids=(observation.revision_id,),
    )
    revision_references = assessment.fixture_revisions
    matching_revision_index = next(
        (
            index
            for index, item in enumerate(revision_references)
            if item.revision_id == revision.revision_id
        ),
        None,
    )
    if matching_revision_index is None:
        revision_references = (*revision_references, revision)
    else:
        previous = revision_references[matching_revision_index]
        revision = replace(
            revision,
            source_capture_ids=tuple(
                dict.fromkeys((*previous.source_capture_ids, *revision.source_capture_ids))
            ),
            source_assertion_ids=tuple(
                dict.fromkeys((*previous.source_assertion_ids, *revision.source_assertion_ids))
            ),
        )
        revision_references = tuple(
            revision if index == matching_revision_index else item
            for index, item in enumerate(revision_references)
        )
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in assessment.scope_assessments),
        provider_attempts=(*assessment.provider_attempts, attempt),
        coverage_evidence=assessment.coverage_evidence,
        fixture_revisions=revision_references,
        identity_resolutions=(*assessment.identity_resolutions, identity),
        freshness_results=assessment.freshness_results,
    )


def _assessment_with_non_membership_conflict(
    store: Store,
    tmp_path: Path,
    assessment: FixtureCoverageAssessment,
) -> FixtureCoverageAssessment:
    scope = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")[0]
    league = league_by_key("premier_league")
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    content = json.dumps(
        {
            "matches": [
                {
                    "date": "2026-09-25",
                    "time": "12:00",
                    "team1": "Conflict United",
                    "team2": "Conflict City",
                    "venue": "South Ground",
                    "score": {},
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    dataset = OpenFootballJSONParser().parse(content, league=league, season=scope.season)
    imported = importer.import_dataset(
        dataset,
        content,
        SourceCaptureInput(
            source_url="https://example.test/f06-venue-conflict.json",
            retrieved_at_utc="2026-09-16T12:30:00+00:00",
            observed_terms="CC0",
            cache_key="f06-venue-conflict",
        ),
    )
    observations = importer.observations_for_capture(imported.source_capture_id)
    assert len(observations) == 1
    reference = assessment.fixture_revisions[0]
    observation = observations[0]
    assert observation.revision_id == reference.revision_id
    fixture_id = reference.fixture_id
    original_capture_id = reference.source_capture_ids[0]
    venue_assertion_ids = (
        deterministic_identifier("source_assertion", f"{original_capture_id}:match-0:venue"),
        deterministic_identifier("source_assertion", f"{imported.source_capture_id}:match-0:venue"),
    )
    with store.transaction() as transaction:
        for assertion_id, capture_id, venue in zip(
            venue_assertion_ids,
            (original_capture_id, imported.source_capture_id),
            ("North Ground", "South Ground"),
            strict=True,
        ):
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("source_assertion", assertion_id)
            )
            transaction.execute(
                """
                INSERT INTO source_assertions (
                    assertion_id, capture_id, origin_id, source_row_key,
                    subject_kind, subject_key, evidence_type, predicate,
                    raw_field_name, raw_value_json, normalized_value_json,
                    evidence_state, unknown_reason, event_time_utc, effective_time_utc,
                    created_at_utc
                ) VALUES (?, ?, NULL, ?, 'FIXTURE', ?, 'FIXTURE', 'venue', ?, ?, ?,
                          'OBSERVED', NULL, NULL, NULL, ?)
                """,
                (
                    assertion_id,
                    capture_id,
                    "match-0",
                    fixture_id,
                    "venue",
                    json.dumps(venue, separators=(",", ":")),
                    json.dumps(venue, separators=(",", ":")),
                    "2026-09-16T12:30:00.000000+00:00",
                ),
            )
            transaction.execute(
                """
                INSERT INTO fixture_revision_assertions (revision_id, assertion_id)
                VALUES (?, ?)
                """,
                (reference.revision_id, assertion_id),
            )
        normalized_values = tuple(
            sorted(
                json.dumps(item, separators=(",", ":")) for item in ("North Ground", "South Ground")
            )
        )
        value_digest = hashlib.sha256(
            json.dumps(normalized_values, separators=(",", ":")).encode()
        ).hexdigest()
        conflict_id = deterministic_identifier(
            "conflict_set", f"FIXTURE:{fixture_id}:venue:{value_digest}"
        )
        transaction.add_identifier_if_missing(CanonicalIdentifier("conflict_set", conflict_id))
        transaction.execute(
            """
            INSERT INTO conflict_sets (
                conflict_id, subject_kind, subject_key, predicate,
                value_digest, status, created_at_utc
            ) VALUES (?, 'FIXTURE', ?, 'venue', ?, 'UNRESOLVED', ?)
            """,
            (conflict_id, fixture_id, value_digest, "2026-09-16T12:30:00.000000+00:00"),
        )
        for assertion_id in venue_assertion_ids:
            transaction.execute(
                """
                INSERT INTO conflict_assertions (conflict_id, assertion_id)
                VALUES (?, ?)
                """,
                (conflict_id, assertion_id),
            )

    updated_reference = replace(
        reference,
        source_capture_ids=tuple(
            dict.fromkeys((*reference.source_capture_ids, imported.source_capture_id))
        ),
        source_assertion_ids=tuple(
            sorted(
                {
                    *reference.source_assertion_ids,
                    *(
                        assertion_id
                        for item in observations
                        for assertion_id in item.source_assertion_ids
                    ),
                    *venue_assertion_ids,
                }
            )
        ),
    )
    attempt = ProviderAttempt(
        attempt_id="venue-conflict-attempt",
        scope_id=scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:30:00.000000+00:00",
        http_status=200,
        capture_id=imported.source_capture_id,
        capture_digest=imported.source_digest,
    )
    identities = (
        *assessment.identity_resolutions,
        FixtureIdentityResolution(
            candidate_id="venue-candidate-0",
            scope_id=scope.scope_id,
            state=FixtureIdentityState.RESOLVED,
            canonical_fixture_id=fixture_id,
            revision_ids=(reference.revision_id,),
            source_capture_ids=(imported.source_capture_id,),
            source_assertion_ids=observation.source_assertion_ids,
        ),
    )
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in assessment.scope_assessments),
        provider_attempts=(*assessment.provider_attempts, attempt),
        coverage_evidence=assessment.coverage_evidence,
        fixture_revisions=tuple(
            updated_reference if item.revision_id == reference.revision_id else item
            for item in assessment.fixture_revisions
        ),
        identity_resolutions=identities,
        freshness_results=assessment.freshness_results,
    )


def _append_revision_outside_assessment(
    store: Store,
    reference: FixtureRevisionReference,
    *,
    status: str,
    source_capture_id: str,
    source_assertion_ids: tuple[str, ...],
) -> str:
    prior = (
        store._connection_for_repository()
        .execute(
            """
        SELECT fixture_id, kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
               source_round
        FROM fixture_revisions WHERE revision_id = ?
        """,
            (reference.revision_id,),
        )
        .fetchone()
    )
    assert prior is not None
    payload = {
        "fixture_status": status,
        "kickoff_local_text": prior[3],
        "kickoff_precision": str(prior[4]),
        "kickoff_state": str(prior[1]),
        "kickoff_utc": prior[2],
        "source_round": prior[5],
    }
    revision_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    revision_id = deterministic_identifier(
        "fixture_revision", f"{reference.fixture_id}:{revision_digest}"
    )
    with store.transaction() as transaction:
        transaction.add_identifier_if_missing(CanonicalIdentifier("fixture_revision", revision_id))
        transaction.execute(
            """
            INSERT INTO fixture_revisions (
                revision_id, fixture_id, predecessor_revision_id, revision_digest,
                kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
                fixture_status, source_round, observed_at_utc, source_capture_id,
                source_assertion_ids_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                str(prior[0]),
                reference.revision_id,
                revision_digest,
                payload["kickoff_state"],
                payload["kickoff_utc"],
                payload["kickoff_local_text"],
                payload["kickoff_precision"],
                status,
                payload["source_round"],
                "2026-09-18T12:00:00.000000+00:00",
                source_capture_id,
                json.dumps(source_assertion_ids, separators=(",", ":")),
                "2026-09-18T12:00:00.000000+00:00",
            ),
        )
        for assertion_id in source_assertion_ids:
            transaction.execute(
                """
                INSERT INTO fixture_revision_assertions (revision_id, assertion_id)
                VALUES (?, ?)
                """,
                (revision_id, assertion_id),
            )
    return revision_id


def _persistable_later_assessment(store: Store, tmp_path: Path) -> FixtureCoverageAssessment:
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    attempts: list[ProviderAttempt] = []
    references: list[FixtureRevisionReference] = []
    identities: list[FixtureIdentityResolution] = []
    for index, (scope, league) in enumerate(zip(scopes, TARGET_LEAGUES, strict=True)):
        if index == 0:
            content = json.dumps(
                {
                    "matches": [
                        {
                            "date": "2026-09-29",
                            "time": "00:00",
                            "team1": "Start United",
                            "team2": "Start City",
                            "score": {},
                        }
                    ]
                },
                separators=(",", ":"),
            ).encode()
            dataset = OpenFootballJSONParser().parse(content, league=league, season=scope.season)
            imported = importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url="https://example.test/premier-later.json",
                    retrieved_at_utc="2026-09-20T12:00:00+00:00",
                    observed_terms="CC0",
                    cache_key="f06-later-premier",
                ),
            )
            observations = importer.observations_for_capture(imported.source_capture_id)
            assert len(observations) == 1
            observation: FixtureCaptureObservation = observations[0]
            assert observation.fixture_id is not None
            assert observation.revision_id is not None
            assert observation.revision_digest is not None
            references.append(
                FixtureRevisionReference(
                    scope_id=scope.scope_id,
                    fixture_id=observation.fixture_id,
                    revision_id=observation.revision_id,
                    revision_digest=observation.revision_digest,
                    source_capture_ids=(imported.source_capture_id,),
                    source_assertion_ids=observation.source_assertion_ids,
                )
            )
            identities.append(
                FixtureIdentityResolution(
                    candidate_id="candidate-later-source-row",
                    scope_id=scope.scope_id,
                    state=FixtureIdentityState.RESOLVED,
                    canonical_fixture_id=observation.fixture_id,
                    revision_ids=(observation.revision_id,),
                )
            )
            capture_id = imported.source_capture_id
            capture_digest = imported.source_digest
        else:
            capture = importer.retain_capture(
                source_kind=SourceKind.OPENFOOTBALL,
                league=league,
                season=scope.season,
                content=f"later-capture-{index}".encode(),
                capture=SourceCaptureInput(
                    source_url=f"https://example.test/{league.key}-later.json",
                    retrieved_at_utc="2026-09-20T12:00:00+00:00",
                    observed_terms="CC0",
                    cache_key=f"f06-later-{index}",
                ),
            )
            capture_id = capture.capture_id
            capture_digest = capture.content_sha256
        attempts.append(
            ProviderAttempt(
                attempt_id=f"later-attempt-{index}",
                scope_id=scope.scope_id,
                provider_id="openfootball-json",
                capability_id="scheduled-fixtures",
                state=ProviderAttemptState.CAPTURED,
                retrieved_at_utc="2026-09-20T12:00:00.000000+00:00",
                http_status=200,
                capture_id=capture_id,
                capture_digest=capture_digest,
            )
        )
    return assess_fixture_coverage(
        scopes=scopes,
        provider_attempts=tuple(attempts),
        coverage_evidence=(),
        fixture_revisions=tuple(references),
        identity_resolutions=tuple(identities),
        freshness_results=(),
    )


def test_all_seven_confirmed_empty_scopes_create_immutable_zero_member_freeze(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_empty_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(assessment)
        health_records = build_provider_health_records(assessment)
        ProviderHealthRepository(store).persist_many(health_records)
        repository = MatchweekMembershipRepository(store, clock=lambda: now)

        frozen = repository.freeze_exact(
            season="2026-27",
            matchweek_friday="2026-09-25",
            assessment_digest=assessment.digest,
            policy_id="matchvet:matchweek-membership",
            policy_version="1",
        )
        replay = repository.get_by_id(frozen.freeze_id)

    assert frozen.schedule_state == "CONFIRMED_EMPTY"
    assert frozen.memberships == ()
    assert len(frozen.scopes) == 7
    assert tuple(scope.coverage_state for scope in frozen.scopes) == ("CONFIRMED_EMPTY",) * 7
    assert len(frozen.provider_health_references) == len(health_records) == 7
    assert frozen.created_at_utc == "2026-09-24T12:00:00.000000+00:00"
    assert replay == frozen


def test_freeze_exact_accepts_all_seven_persisted_attested_v3_scopes(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "20:00", "Arsenal", "Coventry"),),
        )
        repository = FixtureCoverageRepository(store)
        repository.persist(base)
        attestations = []
        for scope_assessment in base.scope_assessments:
            manifest = repository.build_candidate_manifest(base, scope_assessment.scope.scope_id)
            candidate_confirmations = tuple(
                CandidateComparisonConfirmation(
                    candidate_id=entry.candidate_id,
                    identity_matches=True,
                    date_matches=True,
                    kickoff_matches=True,
                    status_matches=True,
                )
                for entry in manifest.entries
            )
            confirmations = OperatorComparisonConfirmations(
                all_official_fixtures_represented=True,
                no_extra_matchvet_fixture=True,
                complete_official_publication_covers_scope=True,
                pairing_calendar_layer_checked=True,
                exact_schedule_layer_checked=True,
                latest_applicable_update_checked=True,
                complete_publication_affirms_empty_scope=manifest.candidate_count == 0,
            )
            attestation = make_operator_coverage_attestation(
                base_assessment=base,
                candidate_manifest=manifest,
                operator_id="offline-operator-1",
                verified_at_utc="2026-09-17T12:00:00.000000+00:00",
                publications=_certification_publications_for_scope(scope_assessment.scope),
                expected_official_fixture_count=manifest.candidate_count,
                candidate_confirmations=candidate_confirmations,
                confirmations=confirmations,
                outcome=OperatorAttestationOutcome.CERTIFIED,
                reason=None,
            )
            attestations.append(repository.persist_attestation(attestation))

        derived = derive_attested_fixture_coverage(base, tuple(attestations))
        repository.persist(derived)
        records = build_provider_health_records(derived)
        ProviderHealthRepository(store).persist_many(records)
        frozen = MatchweekMembershipRepository(store, clock=lambda: now).freeze_exact(
            season="2026-27",
            matchweek_friday="2026-09-25",
            assessment_digest=derived.digest,
            policy_id="matchvet:matchweek-membership",
            policy_version="1",
        )

        assert repository.get(base.digest) == base
        assert repository.get(derived.digest) == derived
        assert frozen.assessment_digest == derived.digest
        assert len(frozen.scopes) == 7
        assert len(frozen.provider_health_references) == 7
        assert len(frozen.memberships) == 1


@pytest.mark.parametrize(
    ("additional_observation", "fake_manual_capture", "expected_freeze"),
    (
        (None, False, True),
        ({"home": "Synthetic East FC", "away": "Synthetic West FC"}, False, False),
        ({"kickoff": "2026-09-25T21:00:00+02:00"}, False, False),
        (None, True, False),
    ),
    ids=(
        "matching-fixture-revision",
        "different-fixture",
        "different-revision",
        "fake-manual-capture",
    ),
)
def test_freeze_exact_verifies_lf05_manual_citation_fixture_support(
    tmp_path: Path,
    additional_observation: dict[str, str] | None,
    fake_manual_capture: bool,
    expected_freeze: bool,
) -> None:
    from test_operator_fixture_observation import _seed_belgian_teams, _valid_input

    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.operator_fixture_observation import OperatorFixtureObservationRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        team_names = ["Synthetic North FC", "Synthetic South FC"]
        if additional_observation is not None:
            team_names.extend(
                additional_observation.get(name, fallback)
                for name, fallback in (
                    ("home", "Synthetic North FC"),
                    ("away", "Synthetic South FC"),
                )
            )
        _seed_belgian_teams(store, tuple(team_names))
        observation_repository = OperatorFixtureObservationRepository(
            store, private_root=tmp_path
        )
        input_facts = {
            "friday": "2026-09-25",
            "kickoff": "2026-09-25T20:00:00+02:00",
            "publication_date": "2026-09-16",
        }
        recorded = observation_repository.record(_valid_input(**input_facts))
        extra_capture_ids: tuple[str, ...] = ()
        if additional_observation is not None:
            extra_input = {**input_facts, **additional_observation}
            extra = observation_repository.record(_valid_input(**extra_input))
            extra_capture_ids = (extra.capture_id,)
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        if fake_manual_capture:
            fake = importer.retain_capture(
                source_kind=SourceKind.OPERATOR_OFFICIAL_FIXTURE_OBSERVATION,
                league=league_by_key("belgian_pro_league"),
                season="2026-27",
                content=b"not a canonical LF05 observation artifact",
                capture=SourceCaptureInput(
                    source_url="https://www.proleague.be/jpl-kalender!",
                    retrieved_at_utc="2026-09-17T12:00:00+00:00",
                    observed_terms="RESEARCH_ONLY:MANUAL_CITATION",
                    cache_key="f06-unverified-lf05-capture",
                ),
            )
            assert fake.source_key == "pro-league-official-manual-citation"
            extra_capture_ids = (fake.capture_id,)
        observations = importer.observations_for_capture(recorded.capture_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.revision_id == recorded.revision_id
        assert observation.revision_digest is not None

        baseline = _persistable_schedule_assessment(store, tmp_path, ())
        belgian_scope = next(
            item.scope
            for item in baseline.scope_assessments
            if item.scope.league_key == "belgian_pro_league"
        )
        evidence = tuple(
            replace(item, affirmatively_empty=False)
            if item.scope_id == belgian_scope.scope_id
            else item
            for item in baseline.coverage_evidence
        )
        manual_revision = FixtureRevisionReference(
            scope_id=belgian_scope.scope_id,
            fixture_id=recorded.fixture_id,
            revision_id=recorded.revision_id,
            revision_digest=observation.revision_digest,
            source_capture_ids=(recorded.capture_id, *extra_capture_ids),
            source_assertion_ids=observation.source_assertion_ids,
        )
        assessment = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=baseline.provider_attempts,
            coverage_evidence=evidence,
            fixture_revisions=(*baseline.fixture_revisions, manual_revision),
            identity_resolutions=(
                *baseline.identity_resolutions,
                FixtureIdentityResolution(
                    candidate_id="candidate-lf05-manual-belgian",
                    scope_id=belgian_scope.scope_id,
                    state=FixtureIdentityState.RESOLVED,
                    canonical_fixture_id=recorded.fixture_id,
                    revision_ids=(recorded.revision_id,),
                    source_capture_ids=(recorded.capture_id,),
                    source_assertion_ids=observation.source_assertion_ids,
                ),
            ),
            freshness_results=baseline.freshness_results,
        )
        coverage_repository = FixtureCoverageRepository(store)
        if fake_manual_capture:
            with pytest.raises(FixtureCoverageIntegrityError, match="not a verified LF05"):
                coverage_repository.persist(assessment)
            return
        coverage_repository.persist(assessment)
        attestations = []
        for scope_assessment in assessment.scope_assessments:
            manifest = coverage_repository.build_candidate_manifest(
                assessment, scope_assessment.scope.scope_id
            )
            candidate_confirmations = tuple(
                CandidateComparisonConfirmation(
                    candidate_id=entry.candidate_id,
                    identity_matches=True,
                    date_matches=True,
                    kickoff_matches=True,
                    status_matches=True,
                )
                for entry in manifest.entries
            )
            attestations.append(
                coverage_repository.persist_attestation(
                    make_operator_coverage_attestation(
                        base_assessment=assessment,
                        candidate_manifest=manifest,
                        operator_id="offline-operator-1",
                        verified_at_utc="2026-09-17T12:00:00.000000+00:00",
                        publications=_certification_publications_for_scope(
                            scope_assessment.scope
                        ),
                        expected_official_fixture_count=manifest.candidate_count,
                        candidate_confirmations=candidate_confirmations,
                        confirmations=OperatorComparisonConfirmations(
                            all_official_fixtures_represented=True,
                            no_extra_matchvet_fixture=True,
                            complete_official_publication_covers_scope=True,
                            pairing_calendar_layer_checked=True,
                            exact_schedule_layer_checked=True,
                            latest_applicable_update_checked=True,
                            complete_publication_affirms_empty_scope=(
                                manifest.candidate_count == 0
                            ),
                        ),
                        outcome=OperatorAttestationOutcome.CERTIFIED,
                        reason=None,
                    )
                )
            )

        derived = derive_attested_fixture_coverage(assessment, tuple(attestations))
        coverage_repository.persist(derived)
        provider_health = build_provider_health_records(derived)
        ProviderHealthRepository(store).persist_many(provider_health)
        if expected_freeze:
            frozen = MatchweekMembershipRepository(store).freeze_exact(
                "2026-27",
                "2026-09-25",
                derived.digest,
                "matchvet:matchweek-membership",
                "1",
            )
        else:
            with pytest.raises(MatchweekMembershipError) as refusal:
                MatchweekMembershipRepository(store).freeze_exact(
                    "2026-27",
                    "2026-09-25",
                    derived.digest,
                    "matchvet:matchweek-membership",
                    "1",
                )
            assert refusal.value.reason_code == "REFERENCE_MISMATCH"

    if expected_freeze:
        assert len(frozen.memberships) == 1
        assert len(frozen.provider_health_references) == len(derived.provider_attempts)
        assert {item.attempt_id for item in frozen.provider_health_references} == {
            item.attempt_id for item in derived.provider_attempts
        }
        assert all(
            item.provider_id != "operator-official-fixture-observation"
            for item in frozen.provider_health_references
        )
        belgian_membership = next(
            item
            for item in frozen.memberships
            if item.scope_id == "belgian_pro_league:2026-27:2026-09-25"
        )
        assert belgian_membership.controlling_revision_id == recorded.revision_id


@pytest.mark.parametrize("attempt_change", ("missing", "wrong_digest"))
def test_automated_fixture_revision_requires_an_exact_provider_attempt(
    tmp_path: Path,
    attempt_change: str,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "20:00", "Arsenal", "Coventry"),),
        )
        reference = baseline.fixture_revisions[0]
        capture_id = reference.source_capture_ids[0]
        source_attempt = next(
            item for item in baseline.provider_attempts if item.capture_id == capture_id
        )
        if attempt_change == "missing":
            attempts = tuple(
                item
                for item in baseline.provider_attempts
                if item.attempt_id != source_attempt.attempt_id
            )
            evidence = tuple(
                item
                for item in baseline.coverage_evidence
                if item.attempt_id != source_attempt.attempt_id
            )
            evidence_ids = {item.evidence_id for item in evidence}
            freshness = tuple(
                item for item in baseline.freshness_results if item.evidence_id in evidence_ids
            )
        else:
            attempts = tuple(
                replace(item, capture_digest="0" * 64)
                if item.attempt_id == source_attempt.attempt_id
                else item
                for item in baseline.provider_attempts
            )
            evidence = baseline.coverage_evidence
            freshness = baseline.freshness_results
        changed = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=attempts,
            coverage_evidence=evidence,
            fixture_revisions=baseline.fixture_revisions,
            identity_resolutions=baseline.identity_resolutions,
            freshness_results=freshness,
        )

        with pytest.raises(FixtureCoverageIntegrityError):
            FixtureCoverageRepository(store).persist(changed)


@pytest.mark.parametrize(
    ("coverage_mode", "expected_state"),
    (
        ("unknown", "UNKNOWN"),
        ("partial", "PARTIAL"),
        ("stale", "STALE"),
    ),
)
def test_incomplete_f01_states_refuse_freeze_without_partial_rows(
    tmp_path: Path, coverage_mode: str, expected_state: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        if coverage_mode == "unknown":
            assessment = _assessment(())
        else:
            assessment = _persistable_empty_assessment(store, tmp_path, coverage_mode=coverage_mode)
        FixtureCoverageRepository(store).persist(assessment)
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

        assert refusal.value.reason_code == "ASSESSMENT_INCOMPLETE"
        assert expected_state in str(refusal.value)
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


@pytest.mark.parametrize(
    "malformation",
    ("missing", "duplicate", "wrong_order", "wrong_season", "wrong_friday"),
)
def test_f01_repository_rejects_malformed_scope_sets_before_f06(
    tmp_path: Path, malformation: str
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageIntegrityError

    assessment = _assessment(())
    scopes = assessment.scope_assessments
    if malformation == "missing":
        malformed_scopes = scopes[:-1]
    elif malformation == "duplicate":
        malformed_scopes = (*scopes[:-1], scopes[0])
    elif malformation == "wrong_order":
        malformed_scopes = (scopes[1], scopes[0], *scopes[2:])
    elif malformation == "wrong_season":
        wrong_scope = FixtureScope(
            scopes[0].scope.league_key,
            "2025-26",
            scopes[0].scope.matchweek_friday,
        )
        malformed_scopes = (replace(scopes[0], scope=wrong_scope), *scopes[1:])
    else:
        wrong_scope = FixtureScope(
            scopes[0].scope.league_key,
            scopes[0].scope.season,
            "2026-10-02",
        )
        malformed_scopes = (replace(scopes[0], scope=wrong_scope), *scopes[1:])
    malformed_assessment = replace(assessment, scope_assessments=malformed_scopes, digest="")

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = FixtureCoverageRepository(store)
        with pytest.raises(FixtureCoverageIntegrityError):
            repository.persist(malformed_assessment)

        assert repository.get(malformed_assessment.digest) is None


def test_freeze_refuses_when_exact_f05_attempt_history_is_missing(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_empty_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(assessment)
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

        assert refusal.value.reason_code == "HEALTH_HISTORY_INCOMPLETE"
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


def test_freeze_references_f05_for_each_attempt_including_unavailable_attempts(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health import FailureState, ProviderAttemptReference

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_empty_assessment(store, tmp_path)
        failed_attempt = ProviderAttempt(
            attempt_id="f06-additional-unavailable-attempt",
            scope_id=baseline.scope_assessments[0].scope.scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:30:00.000000+00:00",
        )
        assessment = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=(*baseline.provider_attempts, failed_attempt),
            coverage_evidence=baseline.coverage_evidence,
            fixture_revisions=baseline.fixture_revisions,
            identity_resolutions=baseline.identity_resolutions,
            freshness_results=baseline.freshness_results,
        )
        FixtureCoverageRepository(store).persist(assessment)
        records = build_provider_health_records(assessment)
        ProviderHealthRepository(store).persist_many(records)
        frozen = MatchweekMembershipRepository(store).freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )

    attempt_ids = {
        reference.attempt_id
        for record in records
        for reference in record.provenance
        if isinstance(reference, ProviderAttemptReference)
    }
    referenced_attempt_ids = {item.attempt_id for item in frozen.provider_health_references}
    failed_record = next(
        record
        for record in records
        if any(
            isinstance(reference, ProviderAttemptReference)
            and reference.attempt_id == failed_attempt.attempt_id
            for reference in record.provenance
        )
    )
    assert frozen.schedule_state == "CONFIRMED_EMPTY"
    assert len(frozen.provider_health_references) == len(records) == 8
    assert referenced_attempt_ids == attempt_ids
    assert failed_record.failure.state is FailureState.FAILED


@pytest.mark.parametrize("corruption", ("record_payload", "wrong_assessment", "wrong_attempt"))
def test_freeze_refuses_corrupt_or_mismatched_exact_f05_history(
    tmp_path: Path, corruption: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_empty_assessment(store, tmp_path)
        coverage_repository = FixtureCoverageRepository(store)
        coverage_repository.persist(assessment)
        records = build_provider_health_records(assessment)
        ProviderHealthRepository(store).persist_many(records)
        other_digest: str | None = None
        if corruption == "wrong_assessment":
            other_assessment = assess_fixture_coverage(
                scopes=tuple(item.scope for item in assessment.scope_assessments),
                provider_attempts=assessment.provider_attempts,
                coverage_evidence=assessment.coverage_evidence,
                fixture_revisions=assessment.fixture_revisions,
                identity_resolutions=assessment.identity_resolutions,
                freshness_results=tuple(
                    replace(
                        item,
                        evaluated_at_utc="2026-09-17T13:00:00.000000+00:00",
                    )
                    for item in assessment.freshness_results
                ),
            )
            coverage_repository.persist(other_assessment)
            other_digest = other_assessment.digest

        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER provider_health_records_no_update")
            if corruption == "record_payload":
                transaction.execute(
                    """
                    UPDATE provider_health_records
                    SET record_json = json_set(record_json, '$.failure.state', 'FAILED')
                    WHERE record_digest = ?
                    """,
                    (records[0].digest,),
                )
            elif corruption == "wrong_assessment":
                assert other_digest is not None
                transaction.execute(
                    "UPDATE provider_health_records SET assessment_digest = ? "
                    "WHERE assessment_digest = ?",
                    (other_digest, assessment.digest),
                )
            else:
                transaction.execute(
                    "UPDATE provider_health_records SET attempt_id = ? WHERE record_digest = ?",
                    ("wrong-attempt-reference", records[0].digest),
                )

        repository = MatchweekMembershipRepository(store)
        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

        assert refusal.value.reason_code == "HEALTH_HISTORY_INCOMPLETE"
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


def test_freeze_refuses_duplicate_records_from_exact_f05_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_empty_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        original_list = ProviderHealthRepository.list_for_assessment

        def duplicate_first_record(
            repository: ProviderHealthRepository, assessment_digest: str
        ) -> tuple[ProviderHealthRecord, ...]:
            records = original_list(repository, assessment_digest)
            return (*records, records[0])

        monkeypatch.setattr(
            ProviderHealthRepository,
            "list_for_assessment",
            duplicate_first_record,
        )
        repository = MatchweekMembershipRepository(store)
        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

        assert refusal.value.reason_code == "HEALTH_HISTORY_INCOMPLETE"
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


def test_f06_retains_exact_f05_records_without_reclassifying_unknown_dimensions(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health import FreshnessState

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Unknown Health United", "Unknown Health City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        expected_records = build_provider_health_records(assessment)
        health_repository = ProviderHealthRepository(store)
        health_repository.persist_many(expected_records)
        repository = MatchweekMembershipRepository(store)
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        replayed_records = health_repository.list_for_assessment(assessment.digest)
        replay = repository.get_by_id(frozen.freeze_id)

    assert {record.digest for record in replayed_records} == {
        record.digest for record in expected_records
    }
    assert all(record.freshness.state is FreshnessState.UNKNOWN for record in replayed_records)
    assert {item.record_digest for item in frozen.provider_health_references} == {
        record.digest for record in replayed_records
    }
    assert replay == frozen


@pytest.mark.parametrize(
    ("season", "friday"),
    (("2025-26", "2026-09-25"), ("2026-27", "2026-10-02")),
)
def test_freeze_refuses_assessment_with_mismatched_explicit_season_or_friday(
    tmp_path: Path, season: str, friday: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_empty_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(assessment)
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                season,
                friday,
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == "SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "assessment_digest",
    ("not-a-digest", "sha256:" + "0" * 64),
)
def test_freeze_refuses_an_invalid_or_missing_exact_assessment_digest(
    tmp_path: Path, assessment_digest: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment_digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == "ASSESSMENT_MISSING"


def test_current_f02_openfootball_assessment_still_fails_f06_completeness_gate(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import MatchweekScheduleState
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    league = TARGET_LEAGUES[0]
    content = (
        b'{"matches":[{"date":"2026-09-25","time":"20:00",'
        b'"team1":"Arsenal","team2":"Coventry","score":{}}]}'
    )
    fetcher = StaticSourceFetcher({openfootball_url(league, "2026-27"): content})
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        seed = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/09/2026,Arsenal,Coventry,,\n"
        importer.import_dataset(
            FootballDataCSVParser().parse(seed, league=league, season="2026-27"),
            seed,
            SourceCaptureInput(
                source_url="https://example.test/known-teams.csv",
                retrieved_at_utc="2026-09-15T12:00:00+00:00",
                observed_terms="restricted test capture",
                cache_key="f06-known-teams",
            ),
        )
        scheduled = FixtureHistoryAcquirer(importer, fetcher).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )
        assessment = scheduled.assessment
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN
    assert assessment.coverage_evidence == ()
    assert refusal.value.reason_code == "ASSESSMENT_INCOMPLETE"


def test_exact_request_reuses_original_bytes_and_changed_assessment_gets_new_identity(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    clock_values = iter(
        (
            datetime(2026, 9, 24, 12, tzinfo=UTC),
            datetime(2026, 9, 24, 13, tzinfo=UTC),
        )
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        original = _persistable_empty_assessment(store, tmp_path)
        changed = assess_fixture_coverage(
            scopes=tuple(item.scope for item in original.scope_assessments),
            provider_attempts=original.provider_attempts,
            coverage_evidence=original.coverage_evidence,
            fixture_revisions=original.fixture_revisions,
            identity_resolutions=original.identity_resolutions,
            freshness_results=tuple(
                replace(item, evaluated_at_utc="2026-09-17T13:00:00.000000+00:00")
                for item in original.freshness_results
            ),
        )
        assessments = FixtureCoverageRepository(store)
        health = ProviderHealthRepository(store)
        assessments.persist(original)
        assessments.persist(changed)
        health.persist_many(build_provider_health_records(original))
        health.persist_many(build_provider_health_records(changed))
        repository = MatchweekMembershipRepository(store, clock=lambda: next(clock_values))

        first = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            original.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        retry = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            original.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        distinct = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            changed.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        replay_first_after_later_freeze = repository.get_by_id(first.freeze_id)
        matchweek_history = repository.list_for_matchweek("2026-27", "2026-09-25")

    assert retry == first
    assert retry.created_at_utc == first.created_at_utc
    assert retry.freeze_digest == first.freeze_digest
    assert distinct.freeze_id != first.freeze_id
    assert distinct.freeze_digest != first.freeze_digest
    assert distinct.assessment_digest == changed.digest
    assert distinct.created_at_utc == "2026-09-24T13:00:00.000000+00:00"
    assert replay_first_after_later_freeze == first
    assert tuple(item.freeze_id for item in matchweek_history) == (
        first.freeze_id,
        distinct.freeze_id,
    )
    assert tuple((item.created_at_utc, item.freeze_id) for item in matchweek_history) == tuple(
        sorted((item.created_at_utc, item.freeze_id) for item in matchweek_history)
    )


def test_persist_exact_is_idempotent_and_rejects_conflicting_content_for_one_identity(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership import freeze_digest as calculate_freeze_digest
    from matchvet.matchweek_membership_repository import (
        MatchweekMembershipIntegrityError,
        MatchweekMembershipRepository,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Persist United", "Persist City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        freeze = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        exact_retry = repository.persist_exact(freeze)
        conflicting_payload = replace(
            freeze,
            created_at_utc="2026-09-24T12:00:01.000000+00:00",
            freeze_digest="sha256:" + "0" * 64,
        )
        conflicting_payload = replace(
            conflicting_payload,
            freeze_digest=calculate_freeze_digest(conflicting_payload),
        )

        with pytest.raises(MatchweekMembershipIntegrityError) as refusal:
            repository.persist_exact(conflicting_payload)

        assert refusal.value.reason_code == "IDENTITY_CONFLICT"
        assert repository.get_by_id(freeze.freeze_id) == freeze

    assert exact_retry == freeze


@pytest.mark.parametrize(
    ("policy_id", "policy_version"),
    (
        ("matchvet:unsupported-membership", "1"),
        ("matchvet:matchweek-membership", "2"),
    ),
)
def test_freeze_refuses_unsupported_policy_identity_or_version(
    tmp_path: Path, policy_id: str, policy_version: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = MatchweekMembershipRepository(store)
        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                "sha256:" + "0" * 64,
                policy_id,
                policy_version,
            )

        assert refusal.value.reason_code == "POLICY_UNSUPPORTED"
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


def test_complete_mixed_scope_freeze_groups_candidates_and_uses_half_open_window(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    rows = (
        ("2026-09-25", "00:00", "Start United", "Start City"),
        ("2026-09-29", "00:00", "Tuesday United", "Tuesday City"),
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store, tmp_path, rows, duplicate_first_candidate=True
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )

        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        replay = repository.get_by_digest(frozen.freeze_digest)

    assert frozen.schedule_state == "COMPLETE"
    assert replay == frozen
    assert len(frozen.scopes) == 7
    assert tuple(scope.coverage_state for scope in frozen.scopes) == (
        "COMPLETE",
        *("CONFIRMED_EMPTY",) * 6,
    )
    assert len(frozen.memberships) == 2
    by_kickoff = {item.controlling_revision.kickoff_utc: item for item in frozen.memberships}
    start = by_kickoff["2026-09-24T23:00:00+00:00"]
    tuesday = by_kickoff["2026-09-28T23:00:00+00:00"]
    assert start.reason_code == "IN_WINDOW_SCHEDULED"
    assert start.decision.value == "INCLUDED"
    assert start.candidate_ids == (
        "candidate-0",
        "candidate-duplicate-provider-row",
    )
    assert tuesday.reason_code == "OUTSIDE_MATCHWEEK_WINDOW"
    assert tuesday.decision.value == "EXCLUDED"
    assert start.controlling_revision.authority_rank == 200
    assert start.controlling_revision_id in {
        item.revision_id for item in assessment.fixture_revisions
    }
    assert start.controlling_revision_digest in {
        item.revision_digest for item in assessment.fixture_revisions
    }
    assert start.controlling_revision.latest_support_retrieved_at_utc == (
        "2026-09-16T12:00:00.000000+00:00"
    )
    assert start.controlling_revision.supports[0].source_key == "openfootball"
    assert start.membership_id != start.fixture_id
    assert start.membership_digest.startswith("sha256:")
    assert frozen.membership_set_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("status", "reason_code"),
    (
        ("COMPLETED", "NOT_SCHEDULED"),
        ("POSTPONED", "POSTPONED"),
        ("CANCELLED", "CANCELLED"),
    ),
)
def test_complete_assessment_can_freeze_determinate_exclusions(
    tmp_path: Path, status: str, reason_code: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Excluded United", "Excluded City"),),
        )
        assessment = _assessment_with_revision(store, baseline, status=status)
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )

        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )

    assert frozen.schedule_state == "COMPLETE"
    assert len(frozen.memberships) == 1
    assert frozen.memberships[0].decision.value == "EXCLUDED"
    assert frozen.memberships[0].reason_code == reason_code


@pytest.mark.parametrize(
    ("date_text", "time_text", "reason_code"),
    (
        ("", "", "STATUS_UNKNOWN"),
        ("2026-09-25", "", "KICKOFF_UNKNOWN"),
    ),
)
def test_membership_refuses_unknown_status_or_kickoff(
    tmp_path: Path, date_text: str, time_text: str, reason_code: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            ((date_text, time_text, "Unknown United", "Unknown City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == reason_code


def test_membership_refuses_unfamiliar_nonempty_status(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Unknown Status United", "Unknown Status City"),),
        )
        assessment = _assessment_with_revision(store, baseline, status="MYSTERY_STATUS")
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == "STATUS_UNKNOWN"


def test_non_membership_conflict_is_recorded_without_changing_decision(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Conflict United", "Conflict City"),),
            venue_for_first="North Ground",
        )
        assessment = _assessment_with_non_membership_conflict(store, tmp_path, baseline)
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(store)

        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )

    assert len(frozen.memberships) == 1
    decision = frozen.memberships[0]
    assert decision.decision.value == "INCLUDED"
    assert decision.reason_code == "IN_WINDOW_SCHEDULED"
    assert decision.reason_codes == ("IN_WINDOW_SCHEDULED", "MATERIAL_SOURCE_CONFLICT")
    assert tuple(item.predicate for item in decision.conflicts) == ("venue",)


def test_equal_top_authority_membership_conflict_refuses_freeze(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Conflict United", "Conflict City"),),
        )
        conflict = _assessment_with_revision(
            store,
            baseline,
            status="SCHEDULED",
            kickoff_utc="2026-09-26T15:00:00+00:00",
            keep_prior_revision=True,
        )
        FixtureCoverageRepository(store).persist(conflict)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(conflict))
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                conflict.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == "MEMBERSHIP_CONFLICT"


def test_authority_selects_structured_provider_and_ignores_revision_outside_f01(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Start United", "Start City"),),
        )
        selected = _assessment_with_higher_authority_revision(store, tmp_path, baseline)
        FixtureCoverageRepository(store).persist(selected)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(selected))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            selected.digest,
            "matchvet:matchweek-membership",
            "1",
        )

        higher_attempt = next(
            item
            for item in selected.provider_attempts
            if item.attempt_id == "higher-authority-attempt"
        )
        assert higher_attempt.capture_id is not None
        high_capture = higher_attempt.capture_id
        source_row = (
            store._connection_for_repository()
            .execute(
                "SELECT source_id FROM source_captures WHERE capture_id = ?",
                (high_capture,),
            )
            .fetchone()
        )
        assert source_row is not None
        high_assertions = tuple(
            str(row[0])
            for row in store._connection_for_repository().execute(
                """
                SELECT assertion_id FROM source_assertions
                WHERE capture_id = ? AND subject_key = ? ORDER BY assertion_id
                """,
                (high_capture, selected.fixture_revisions[0].fixture_id),
            )
        )
        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER source_identities_no_update")
            transaction.execute(
                "UPDATE source_identities SET source_class = 'OFFICIAL_COMPETITION' "
                "WHERE source_id = ?",
                (str(source_row[0]),),
            )
            transaction.execute(
                """
                CREATE TRIGGER source_identities_no_update
                BEFORE UPDATE ON source_identities
                BEGIN SELECT RAISE(ABORT, 'source identities are immutable'); END
                """
            )
        # A later rank-500 revision is outside the selected F01 and cannot change replay.
        _append_revision_outside_assessment(
            store,
            selected.fixture_revisions[0],
            status="CANCELLED",
            source_capture_id=high_capture,
            source_assertion_ids=high_assertions,
        )
        replay = repository.get_by_id(frozen.freeze_id)

    decision = frozen.memberships[0]
    assert decision.decision.value == "INCLUDED"
    assert decision.controlling_revision.authority_rank == 300
    assert "football-data.co.uk" in {
        item.source_key for item in decision.controlling_revision.supports
    }
    assert decision.controlling_revision_id in {
        item.revision_id for item in selected.fixture_revisions
    }
    assert decision.controlling_revision.authority_rank == 300
    assert replay == frozen


def test_authority_latest_support_precedes_revision_id_and_digest(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Start United", "Start City"),),
        )
        older = _assessment_with_higher_authority_revision(
            store,
            tmp_path,
            baseline,
            kickoff="11:00",
            retrieved_at="2026-09-17T12:00:00+00:00",
            cache_key="f06-authority-older",
            attempt_id="higher-authority-older-attempt",
            candidate_id="candidate-higher-authority-older",
        )
        latest = _assessment_with_higher_authority_revision(
            store,
            tmp_path,
            older,
            kickoff="13:00",
            retrieved_at="2026-09-18T12:00:00+00:00",
            cache_key="f06-authority-latest",
            attempt_id="higher-authority-latest-attempt",
            candidate_id="candidate-higher-authority-latest",
        )
        FixtureCoverageRepository(store).persist(latest)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(latest))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            latest.digest,
            "matchvet:matchweek-membership",
            "1",
        )

    decision = frozen.memberships[0]
    latest_attempt = next(
        attempt
        for attempt in latest.provider_attempts
        if attempt.attempt_id == "higher-authority-latest-attempt"
    )
    assert latest_attempt.capture_id is not None
    expected_revision = next(
        reference
        for reference in latest.fixture_revisions
        if latest_attempt.capture_id in reference.source_capture_ids
    )
    assert decision.controlling_revision.authority_rank == 300
    assert decision.controlling_revision.latest_support_retrieved_at_utc == (
        "2026-09-18T12:00:00.000000+00:00"
    )
    assert decision.controlling_revision_id == expected_revision.revision_id


def test_authority_revision_id_breaks_equal_rank_and_support_time_ties(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Tie United", "Tie City"),),
        )
        first = _assessment_with_revision(
            store,
            baseline,
            status="SCHEDULED",
            source_round="tie-break-a",
        )
        second = _assessment_with_revision(
            store,
            baseline,
            status="SCHEDULED",
            source_round="tie-break-z",
        )
        revision_references = (first.fixture_revisions[0], second.fixture_revisions[0])
        combined_identity = replace(
            baseline.identity_resolutions[0],
            revision_ids=tuple(item.revision_id for item in revision_references),
        )
        combined = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=baseline.provider_attempts,
            coverage_evidence=baseline.coverage_evidence,
            fixture_revisions=revision_references,
            identity_resolutions=(combined_identity,),
            freshness_results=baseline.freshness_results,
        )
        FixtureCoverageRepository(store).persist(combined)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(combined))
        frozen = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        ).freeze_exact(
            "2026-27",
            "2026-09-25",
            combined.digest,
            "matchvet:matchweek-membership",
            "1",
        )

    decision = frozen.memberships[0]
    assert len(decision.evaluated_revisions) == 2
    assert len({item.authority_rank for item in decision.evaluated_revisions}) == 1
    assert len({item.latest_support_retrieved_at_utc for item in decision.evaluated_revisions}) == 1
    assert decision.controlling_revision_id == max(
        item.revision_id for item in decision.evaluated_revisions
    )


def test_later_conflict_set_does_not_change_exact_freeze_replay(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Start United", "Start City"),),
        )
        selected = _assessment_with_higher_authority_revision(
            store,
            tmp_path,
            baseline,
            kickoff="13:00",
            retrieved_at="2026-09-17T13:00:00+00:00",
            cache_key="f06-replay-conflict-initial",
        )
        FixtureCoverageRepository(store).persist(selected)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(selected))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            selected.digest,
            "matchvet:matchweek-membership",
            "1",
        )

        repeated_content = (
            b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC\n"
            b"E0,25/09/2026,13:00,Start United,Start City,,,,,,,\n"
        )
        repeated_dataset = FootballDataCSVParser().parse(
            repeated_content,
            league=league_by_key("premier_league"),
            season="2026-27",
        )
        later_importer = FixtureHistoryImporter(store, private_root=tmp_path)
        later_importer.import_dataset(
            repeated_dataset,
            repeated_content,
            SourceCaptureInput(
                source_url="https://example.test/football-data-repeated.csv",
                retrieved_at_utc="2026-09-18T10:00:00+00:00",
                observed_terms="restricted test capture",
                cache_key="f06-replay-conflict-repeated",
            ),
        )

        later_content = (
            b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC\n"
            b"E0,25/09/2026,14:00,Start United,Start City,,,,,,,\n"
        )
        later_dataset = FootballDataCSVParser().parse(
            later_content,
            league=league_by_key("premier_league"),
            season="2026-27",
        )
        later_importer.import_dataset(
            later_dataset,
            later_content,
            SourceCaptureInput(
                source_url="https://example.test/football-data-later.csv",
                retrieved_at_utc="2026-09-18T12:00:00+00:00",
                observed_terms="restricted test capture",
                cache_key="f06-replay-conflict-later",
            ),
        )

        replay = repository.get_by_id(frozen.freeze_id)

    assert replay == frozen


def test_policy_documents_the_existing_t05_revision_tie_break() -> None:
    from matchvet.matchweek_membership import membership_policy_document

    policy = membership_policy_document()
    authority = policy["authority"]
    assert isinstance(authority, dict)

    assert authority["selection_order"] == [
        "authority_rank_desc",
        "latest_support_retrieved_at_utc_desc",
        "revision_id_desc",
        "revision_digest_desc",
    ]


def test_unresolved_identity_is_a_specific_f06_refusal(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        baseline = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Identity United", "Identity City"),),
        )
        identity = baseline.identity_resolutions[0]
        unresolved = replace(
            identity,
            state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
            canonical_fixture_id=None,
            reason_code="IDENTITY_UNRESOLVED",
        )
        assessment = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=baseline.provider_attempts,
            coverage_evidence=baseline.coverage_evidence,
            fixture_revisions=baseline.fixture_revisions,
            identity_resolutions=(unresolved,),
            freshness_results=baseline.freshness_results,
        )
        FixtureCoverageRepository(store).persist(assessment)
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipError) as refusal:
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

    assert refusal.value.reason_code == "IDENTITY_UNRESOLVED"


def test_post_freeze_observations_append_exact_changes_without_mutating_membership(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    clock_values = iter(
        (
            datetime(2026, 9, 24, 12, tzinfo=UTC),
            datetime(2026, 9, 25, 12, tzinfo=UTC),
            datetime(2026, 9, 26, 12, tzinfo=UTC),
        )
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        initial = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "00:00", "Start United", "Start City"),),
        )
        FixtureCoverageRepository(store).persist(initial)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(initial))
        repository = MatchweekMembershipRepository(store, clock=lambda: next(clock_values))
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            initial.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        before = repository.get_by_id(frozen.freeze_id)

        later = _persistable_later_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(later)
        scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
        absence_only = _assessment(
            (
                ProviderAttempt(
                    attempt_id="absence-only-attempt",
                    scope_id=scopes[0].scope_id,
                    provider_id="openfootball-json",
                    capability_id="scheduled-fixtures",
                    state=ProviderAttemptState.UNAVAILABLE,
                    retrieved_at_utc="2026-09-21T12:00:00.000000+00:00",
                ),
            )
        )
        FixtureCoverageRepository(store).persist(absence_only)

        moved = repository.append_observation(frozen.freeze_id, later.digest)
        moved_retry = repository.append_observation(frozen.freeze_id, later.digest)
        absent = repository.append_observation(frozen.freeze_id, absence_only.digest)
        listed = repository.list_observations(frozen.freeze_id)
        after = repository.get_by_id(frozen.freeze_id)

    assert moved.assessment_state == "UNKNOWN"
    assert {item.change_code.value for item in moved.changes} == {
        "IDENTITY_RESOLVED",
        "MOVED_OUT",
        "RESCHEDULED",
        "REVISION_OBSERVED",
    }
    assert all(item.fixture_id == frozen.memberships[0].fixture_id for item in moved.changes)
    assert all(item.source_capture_ids and item.source_assertion_ids for item in moved.changes)
    assert moved.recorded_at_utc == "2026-09-25T12:00:00.000000+00:00"
    assert moved_retry == moved
    assert absent.assessment_state == "UNKNOWN"
    assert absent.changes == ()
    assert tuple(item.observation_id for item in listed) == (
        moved.observation_id,
        absent.observation_id,
    )
    assert before == after == frozen


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    (
        ("added_in_window", "ADDED_IN_WINDOW"),
        ("moved_in", "MOVED_IN"),
        ("postponed", "POSTPONED"),
        ("cancelled", "CANCELLED"),
        ("kickoff_corrected", "KICKOFF_CORRECTED"),
        ("source_conflict", "SOURCE_CONFLICT"),
    ),
)
def test_post_freeze_observation_records_each_supported_change(
    tmp_path: Path, scenario: str, expected_code: str
) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        if scenario == "added_in_window":
            initial = _persistable_empty_assessment(store, tmp_path)
            later = _persistable_schedule_assessment(
                store,
                tmp_path,
                (("2026-09-25", "12:00", "Start United", "Start City"),),
            )
        else:
            original_kickoff = "2026-09-29" if scenario == "moved_in" else "2026-09-25"
            initial = _persistable_schedule_assessment(
                store,
                tmp_path,
                ((original_kickoff, "12:00", "Start United", "Start City"),),
            )
            if scenario == "moved_in":
                later = _assessment_with_revision(
                    store,
                    initial,
                    status="SCHEDULED",
                    kickoff_utc="2026-09-25T12:00:00+00:00",
                )
            elif scenario in {"postponed", "cancelled"}:
                later = _assessment_with_revision(
                    store,
                    initial,
                    status=scenario.upper(),
                )
            elif scenario == "kickoff_corrected":
                later = _assessment_with_revision(
                    store,
                    initial,
                    status="SCHEDULED",
                    kickoff_utc="2026-09-25T13:00:00+00:00",
                )
            else:
                later = _assessment_with_higher_authority_revision(
                    store,
                    tmp_path,
                    initial,
                    kickoff="13:00",
                    cache_key="f06-observation-source-conflict",
                )

        coverage = FixtureCoverageRepository(store)
        coverage.persist(initial)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(initial))
        coverage.persist(later)
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            initial.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        observation = repository.append_observation(frozen.freeze_id, later.digest)
        replay = repository.get_by_id(frozen.freeze_id)

    assert expected_code in {item.change_code.value for item in observation.changes}
    assert replay == frozen


def test_failed_child_write_rolls_back_the_complete_freeze(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import (
        MatchweekMembershipPersistenceError,
        MatchweekMembershipRepository,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Atomic United", "Atomic City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        with store.transaction() as transaction:
            transaction.execute(
                """
                CREATE TRIGGER f06_test_reject_health_reference
                BEFORE INSERT ON v2_matchweek_membership_health_refs
                BEGIN SELECT RAISE(ABORT, 'test child-write failure'); END
                """
            )
        repository = MatchweekMembershipRepository(store)

        with pytest.raises(MatchweekMembershipPersistenceError):
            repository.freeze_exact(
                "2026-27",
                "2026-09-25",
                assessment.digest,
                "matchvet:matchweek-membership",
                "1",
            )

        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()
        assert (
            store._connection_for_repository()
            .execute("SELECT count(*) FROM v2_matchweek_membership_decisions")
            .fetchone()[0]
            == 0
        )


def test_corrupt_relational_membership_child_refuses_exact_replay(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import (
        MatchweekMembershipIntegrityError,
        MatchweekMembershipRepository,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Replay United", "Replay City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER v2_matchweek_membership_decisions_no_delete")
            transaction.execute(
                "DELETE FROM v2_matchweek_membership_decisions WHERE freeze_id = ?",
                (frozen.freeze_id,),
            )

        with pytest.raises(MatchweekMembershipIntegrityError):
            repository.get_by_id(frozen.freeze_id)


@pytest.mark.parametrize(
    "corruption",
    (
        "f01_assessment",
        "f05_record",
        "fixture_revision",
        "source_capture",
        "source_assertion",
        "authority_snapshot",
        "freeze_root",
        "health_child_reference",
    ),
)
def test_corrupt_immutable_reference_refuses_exact_replay(tmp_path: Path, corruption: str) -> None:
    from matchvet.matchweek_membership_repository import (
        MatchweekMembershipIntegrityError,
        MatchweekMembershipRepository,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Corruption United", "Corruption City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        membership = frozen.memberships[0]
        connection = store._connection_for_repository()

        with store.transaction() as transaction:
            if corruption == "f01_assessment":
                transaction.execute("DROP TRIGGER fixture_coverage_assessments_no_update")
                transaction.execute(
                    """
                    UPDATE fixture_coverage_assessments
                    SET assessment_json = json_set(assessment_json, '$.schedule_state', 'PARTIAL')
                    WHERE assessment_digest = ?
                    """,
                    (assessment.digest,),
                )
            elif corruption == "f05_record":
                health = frozen.provider_health_references[0]
                transaction.execute("DROP TRIGGER provider_health_records_no_update")
                transaction.execute(
                    """
                    UPDATE provider_health_records
                    SET record_json = json_set(record_json, '$.failure.state', 'FAILED')
                    WHERE record_digest = ?
                    """,
                    (health.record_digest,),
                )
            elif corruption == "fixture_revision":
                transaction.execute("DROP TRIGGER fixture_revisions_no_update")
                transaction.execute(
                    "UPDATE fixture_revisions SET fixture_status = 'CANCELLED' "
                    "WHERE revision_id = ?",
                    (membership.controlling_revision_id,),
                )
            elif corruption == "source_capture":
                capture_id = membership.controlling_revision.source_capture_ids[0]
                transaction.execute("DROP TRIGGER source_captures_no_update")
                transaction.execute(
                    "UPDATE source_captures SET content_sha256 = ? WHERE capture_id = ?",
                    ("f" * 64, capture_id),
                )
            elif corruption == "source_assertion":
                assertion_id = membership.controlling_revision.source_assertion_ids[0]
                old_capture = connection.execute(
                    "SELECT capture_id FROM source_assertions WHERE assertion_id = ?",
                    (assertion_id,),
                ).fetchone()[0]
                other_capture = connection.execute(
                    "SELECT capture_id FROM source_captures WHERE capture_id <> ? LIMIT 1",
                    (old_capture,),
                ).fetchone()[0]
                transaction.execute("DROP TRIGGER source_assertions_no_update")
                transaction.execute(
                    "UPDATE source_assertions SET capture_id = ? WHERE assertion_id = ?",
                    (other_capture, assertion_id),
                )
            elif corruption == "authority_snapshot":
                row = transaction.execute(
                    "SELECT freeze_json FROM v2_matchweek_membership_freezes WHERE freeze_id = ?",
                    (frozen.freeze_id,),
                ).fetchone()
                payload = json.loads(str(row[0]))
                payload["memberships"][0]["evaluated_revisions"][0]["supports"][0][
                    "authority_rank"
                ] += 1
                transaction.execute("DROP TRIGGER v2_matchweek_membership_freezes_no_update")
                transaction.execute(
                    "UPDATE v2_matchweek_membership_freezes SET freeze_json = ? "
                    "WHERE freeze_id = ?",
                    (
                        json.dumps(
                            payload,
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        frozen.freeze_id,
                    ),
                )
            elif corruption == "freeze_root":
                row = transaction.execute(
                    "SELECT freeze_json FROM v2_matchweek_membership_freezes WHERE freeze_id = ?",
                    (frozen.freeze_id,),
                ).fetchone()
                payload = json.loads(str(row[0]))
                changed_timestamp = "2026-09-24T12:00:01.000000+00:00"
                payload["created_at_utc"] = changed_timestamp
                transaction.execute("DROP TRIGGER v2_matchweek_membership_freezes_no_update")
                transaction.execute(
                    "UPDATE v2_matchweek_membership_freezes "
                    "SET freeze_json = ?, created_at_utc = ? WHERE freeze_id = ?",
                    (
                        json.dumps(
                            payload,
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        changed_timestamp,
                        frozen.freeze_id,
                    ),
                )
            else:
                health = frozen.provider_health_references[0]
                transaction.execute("DROP TRIGGER v2_matchweek_membership_health_refs_no_update")
                transaction.execute(
                    """
                    UPDATE v2_matchweek_membership_health_refs
                    SET provider_id = 'corrupt-provider'
                    WHERE freeze_id = ? AND attempt_id = ?
                    """,
                    (frozen.freeze_id, health.attempt_id),
                )

        with pytest.raises(MatchweekMembershipIntegrityError):
            repository.get_by_id(frozen.freeze_id)


def test_v2_freeze_member_health_and_observation_rows_reject_mutation(tmp_path: Path) -> None:
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "12:00", "Immutable United", "Immutable City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repository = MatchweekMembershipRepository(
            store,
            clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )
        frozen = repository.freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        later = _persistable_later_assessment(store, tmp_path)
        FixtureCoverageRepository(store).persist(later)
        observation = repository.append_observation(frozen.freeze_id, later.digest)

        mutations = (
            (
                "UPDATE v2_matchweek_membership_freezes SET created_at_utc = created_at_utc "
                "WHERE freeze_id = ?",
                (frozen.freeze_id,),
            ),
            (
                "DELETE FROM v2_matchweek_membership_freezes WHERE freeze_id = ?",
                (frozen.freeze_id,),
            ),
            (
                "UPDATE v2_matchweek_membership_decisions SET reason_code = reason_code "
                "WHERE membership_id = ?",
                (frozen.memberships[0].membership_id,),
            ),
            (
                "DELETE FROM v2_matchweek_membership_decisions WHERE membership_id = ?",
                (frozen.memberships[0].membership_id,),
            ),
            (
                "UPDATE v2_matchweek_membership_health_refs SET capability_id = capability_id "
                "WHERE freeze_id = ?",
                (frozen.freeze_id,),
            ),
            (
                "DELETE FROM v2_matchweek_membership_health_refs WHERE freeze_id = ?",
                (frozen.freeze_id,),
            ),
            (
                "UPDATE v2_matchweek_membership_observations "
                "SET assessment_state = assessment_state WHERE observation_id = ?",
                (observation.observation_id,),
            ),
            (
                "DELETE FROM v2_matchweek_membership_observations WHERE observation_id = ?",
                (observation.observation_id,),
            ),
        )
        for statement, parameters in mutations:
            with pytest.raises(sqlite3.IntegrityError), store.transaction() as transaction:
                transaction.execute(statement, parameters)

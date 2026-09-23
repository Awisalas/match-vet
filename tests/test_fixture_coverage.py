from __future__ import annotations

import pytest

from matchvet.fixture_coverage import (
    CoverageBasis,
    CoverageBasisKind,
    CoverageBounds,
    CoverageFreshnessResult,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    FixtureScope,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    ScopeCoverageState,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)

SCOPES = fixture_scopes_for_matchweek("2026-09-18", season="2026-27")
PREMIER_SCOPE = SCOPES[0]
DEFAULT_COVERAGE_BASIS = CoverageBasis(
    kind=CoverageBasisKind.VERSIONED_SOURCE_CONTRACT,
    reference_id="fixture-feed",
    version="v1",
)


def _complete_scope_inputs(
    scope: FixtureScope,
    *,
    suffix: str,
    affirmatively_empty: bool = False,
    coverage_basis: CoverageBasis | None = DEFAULT_COVERAGE_BASIS,
    permitted_for_use: bool = True,
    provider_use_policy_id: str | None = "provider-use-policy-v1",
    provider_competition_key: str | None = None,
    provider_season: str | None = None,
    bounds: CoverageBounds | None = None,
    required_partition_ids: tuple[str, ...] = (),
    accounted_partition_ids: tuple[str, ...] = (),
    pagination_exhausted: bool = True,
    current: bool = True,
) -> tuple[
    ProviderAttempt,
    ProviderCoverageEvidence,
    FixtureRevisionReference,
    FixtureIdentityResolution,
    CoverageFreshnessResult,
]:
    attempt = ProviderAttempt(
        attempt_id=f"attempt-{suffix}",
        scope_id=scope.scope_id,
        provider_id="example-feed",
        capability_id="upcoming-fixtures-v1",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        http_status=200,
        capture_id=f"capture-{suffix}",
        capture_digest=f"sha256:capture-{suffix}",
    )
    evidence = ProviderCoverageEvidence(
        evidence_id=f"coverage-{suffix}",
        attempt_id=attempt.attempt_id,
        scope_id=scope.scope_id,
        provider_competition_key=provider_competition_key or scope.league_key,
        provider_season=provider_season or scope.season,
        capture_id=f"capture-{suffix}",
        capture_digest=f"sha256:capture-{suffix}",
        coverage_basis=coverage_basis,
        bounds=bounds
        or CoverageBounds(start_utc=scope.window_start_utc, end_utc=scope.window_end_utc),
        provider_use_policy_id=provider_use_policy_id,
        permitted_for_use=permitted_for_use,
        required_partition_ids=required_partition_ids,
        accounted_partition_ids=accounted_partition_ids,
        pagination_exhausted=pagination_exhausted,
        affirmatively_empty=affirmatively_empty,
    )
    revision = FixtureRevisionReference(
        scope_id=scope.scope_id,
        fixture_id=f"fixture-{suffix}",
        revision_id=f"revision-{suffix}",
        revision_digest=f"sha256:revision-{suffix}",
        source_capture_ids=(f"capture-{suffix}",),
        source_assertion_ids=(f"assertion-{suffix}",),
    )
    identity = FixtureIdentityResolution(
        candidate_id=f"candidate-{suffix}",
        scope_id=scope.scope_id,
        state=FixtureIdentityState.RESOLVED,
        canonical_fixture_id=revision.fixture_id,
        revision_ids=(revision.revision_id,),
    )
    freshness = CoverageFreshnessResult(
        evidence_id=evidence.evidence_id,
        policy_id="freshness-policy-v1",
        evaluated_at_utc="2026-09-15T12:05:00.000000+00:00",
        is_current=current,
    )
    return attempt, evidence, revision, identity, freshness


def test_v2_scope_factory_uses_the_seven_target_leagues_and_existing_matchweek_window() -> None:
    scopes = fixture_scopes_for_matchweek("2026-09-18", season="2026-27")

    assert tuple(scope.league_key for scope in scopes) == (
        "premier_league",
        "serie_a",
        "la_liga",
        "bundesliga",
        "ligue_1",
        "liga_portugal",
        "belgian_pro_league",
    )
    assert all(scope.season == "2026-27" for scope in scopes)
    assert {(scope.window_start_utc, scope.window_end_utc) for scope in scopes} == {
        ("2026-09-17T23:00:00.000000+00:00", "2026-09-21T23:00:00.000000+00:00")
    }


def test_provider_attempt_outcome_is_independent_of_http_status() -> None:
    malformed_capture = ProviderAttempt(
        attempt_id="attempt-malformed",
        scope_id="premier_league:2026-27:2026-09-18",
        provider_id="example-feed",
        capability_id="upcoming-fixtures-v1",
        state=ProviderAttemptState.MALFORMED,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-malformed",
        capture_digest="sha256:malformed",
    )

    assert malformed_capture.state is ProviderAttemptState.MALFORMED
    assert malformed_capture.http_status == 200
    assert len({state.value for state in ProviderAttemptState}) == 3


def test_parsed_rows_and_revision_identity_without_coverage_claim_remain_unknown() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-premier",
        scope_id=PREMIER_SCOPE.scope_id,
        provider_id="example-feed",
        capability_id="upcoming-fixtures-v1",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-premier",
        capture_digest="sha256:capture-premier",
    )
    evidence = ProviderCoverageEvidence(
        evidence_id="coverage-premier",
        attempt_id=attempt.attempt_id,
        scope_id=PREMIER_SCOPE.scope_id,
        provider_competition_key="premier_league",
        provider_season="2026-27",
        capture_id="capture-premier",
        capture_digest="sha256:capture-premier",
        coverage_basis=None,
        bounds=CoverageBounds(
            start_utc=PREMIER_SCOPE.window_start_utc,
            end_utc=PREMIER_SCOPE.window_end_utc,
        ),
        pagination_exhausted=True,
    )
    revision = FixtureRevisionReference(
        scope_id=PREMIER_SCOPE.scope_id,
        fixture_id="fixture-arsenal-coventry",
        revision_id="revision-1",
        revision_digest="sha256:revision-1",
        source_capture_ids=("capture-premier",),
        source_assertion_ids=("assertion-1",),
    )
    identity = FixtureIdentityResolution(
        candidate_id="candidate-1",
        scope_id=PREMIER_SCOPE.scope_id,
        state=FixtureIdentityState.RESOLVED,
        canonical_fixture_id=revision.fixture_id,
        revision_ids=(revision.revision_id,),
    )
    freshness = CoverageFreshnessResult(
        evidence_id=evidence.evidence_id,
        policy_id="freshness-policy-v1",
        evaluated_at_utc="2026-09-15T12:05:00.000000+00:00",
        is_current=True,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(attempt,),
        coverage_evidence=(evidence,),
        fixture_revisions=(revision,),
        identity_resolutions=(identity,),
        freshness_results=(freshness,),
    )

    premier = assessment.scope_assessments[0]
    assert premier.coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN
    assert premier.fixture_revisions == (revision,)
    assert premier.provider_attempt_ids == (attempt.attempt_id,)


def test_coverage_basis_must_identify_a_contract_or_provider_metadata() -> None:
    with pytest.raises(ValueError, match="Coverage Basis"):
        CoverageBasis(
            kind=CoverageBasisKind.VERSIONED_SOURCE_CONTRACT,
            reference_id="fixture-feed",
        )

    with pytest.raises(ValueError, match="Coverage Basis"):
        CoverageBasis(kind="downloaded", reference_id="fixture-feed")  # type: ignore[arg-type]


def test_explicit_provider_metadata_can_support_a_full_coverage_claim() -> None:
    row = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="explicit-metadata",
        coverage_basis=CoverageBasis(
            kind=CoverageBasisKind.EXPLICIT_PROVIDER_METADATA,
            reference_id="metadata-schedule-complete",
        ),
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.COMPLETE


@pytest.mark.parametrize(
    ("source_scope", "source_state", "source_capture_id"),
    (
        (SCOPES[1], ProviderAttemptState.CAPTURED, "foreign-scope-capture"),
        (PREMIER_SCOPE, ProviderAttemptState.MALFORMED, "malformed-capture"),
    ),
)
def test_fixture_revision_requires_a_captured_source_in_its_scope(
    source_scope: FixtureScope,
    source_state: ProviderAttemptState,
    source_capture_id: str,
) -> None:
    row = _complete_scope_inputs(PREMIER_SCOPE, suffix="dangling-revision-source")
    source_attempt = ProviderAttempt(
        attempt_id="attempt-invalid-revision-source",
        scope_id=source_scope.scope_id,
        provider_id="example-feed",
        capability_id="upcoming-fixtures-v1",
        state=source_state,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        capture_id=source_capture_id,
        capture_digest=f"sha256:{source_capture_id}",
    )
    revision = FixtureRevisionReference(
        scope_id=row[2].scope_id,
        fixture_id=row[2].fixture_id,
        revision_id=row[2].revision_id,
        revision_digest=row[2].revision_digest,
        source_capture_ids=(source_capture_id,),
        source_assertion_ids=row[2].source_assertion_ids,
    )

    with pytest.raises(ValueError, match="captured Provider Attempt"):
        assess_fixture_coverage(
            scopes=SCOPES,
            provider_attempts=(row[0], source_attempt),
            coverage_evidence=(row[1],),
            fixture_revisions=(revision,),
            identity_resolutions=(row[3],),
            freshness_results=(row[4],),
        )


def test_current_full_scope_evidence_for_all_seven_leagues_is_complete_and_deterministic() -> None:
    rows = tuple(_complete_scope_inputs(scope, suffix=scope.league_key) for scope in SCOPES)
    attempts = tuple(row[0] for row in rows)
    evidence = tuple(row[1] for row in rows)
    revisions = tuple(row[2] for row in rows)
    identities = tuple(row[3] for row in rows)
    freshness = tuple(row[4] for row in rows)

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=attempts,
        coverage_evidence=evidence,
        fixture_revisions=revisions,
        identity_resolutions=identities,
        freshness_results=freshness,
    )
    replay = assess_fixture_coverage(
        scopes=tuple(reversed(SCOPES)),
        provider_attempts=tuple(reversed(attempts)),
        coverage_evidence=tuple(reversed(evidence)),
        fixture_revisions=tuple(reversed(revisions)),
        identity_resolutions=tuple(reversed(identities)),
        freshness_results=tuple(reversed(freshness)),
    )

    assert assessment.schedule_state is MatchweekScheduleState.COMPLETE
    assert all(
        item.coverage_state is ScopeCoverageState.COMPLETE for item in assessment.scope_assessments
    )
    assert assessment.contract_version == "fixture-coverage-v2-v2"
    assert assessment.schema_version == 2
    assert assessment.digest.startswith("sha256:")
    assert replay.digest == assessment.digest


def test_matchweek_can_mix_complete_nonempty_and_confirmed_empty_scopes() -> None:
    nonempty_rows = tuple(
        _complete_scope_inputs(scope, suffix=scope.league_key) for scope in SCOPES[:-1]
    )
    empty_attempt, empty_evidence, _, _, empty_freshness = _complete_scope_inputs(
        SCOPES[-1], suffix=SCOPES[-1].league_key, affirmatively_empty=True
    )
    attempts = (*tuple(row[0] for row in nonempty_rows), empty_attempt)
    evidence = (*tuple(row[1] for row in nonempty_rows), empty_evidence)
    revisions = tuple(row[2] for row in nonempty_rows)
    identities = tuple(row[3] for row in nonempty_rows)
    freshness = (*tuple(row[4] for row in nonempty_rows), empty_freshness)

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=attempts,
        coverage_evidence=evidence,
        fixture_revisions=revisions,
        identity_resolutions=identities,
        freshness_results=freshness,
    )

    assert assessment.schedule_state is MatchweekScheduleState.COMPLETE
    assert assessment.scope_assessments[-1].coverage_state is ScopeCoverageState.CONFIRMED_EMPTY


def test_all_seven_affirmatively_empty_scopes_produce_confirmed_empty() -> None:
    rows = tuple(
        _complete_scope_inputs(scope, suffix=scope.league_key, affirmatively_empty=True)
        for scope in SCOPES
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=tuple(row[0] for row in rows),
        coverage_evidence=tuple(row[1] for row in rows),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=tuple(row[4] for row in rows),
    )

    assert assessment.schedule_state is MatchweekScheduleState.CONFIRMED_EMPTY
    assert all(
        item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY
        for item in assessment.scope_assessments
    )


def test_unresolved_fixture_revision_cannot_be_ignored_in_confirmed_empty_assessment() -> None:
    rows = tuple(
        _complete_scope_inputs(scope, suffix=scope.league_key, affirmatively_empty=True)
        for scope in SCOPES
    )

    with pytest.raises(ValueError, match="Fixture Identity Resolution"):
        assess_fixture_coverage(
            scopes=SCOPES,
            provider_attempts=tuple(row[0] for row in rows),
            coverage_evidence=tuple(row[1] for row in rows),
            fixture_revisions=(rows[0][2],),
            identity_resolutions=(),
            freshness_results=tuple(row[4] for row in rows),
        )


def test_missing_league_scope_evidence_makes_current_matchweek_partial() -> None:
    rows = tuple(_complete_scope_inputs(scope, suffix=scope.league_key) for scope in SCOPES[:-1])

    assessment = assess_fixture_coverage(
        scopes=SCOPES[:-1],
        provider_attempts=tuple(row[0] for row in rows),
        coverage_evidence=tuple(row[1] for row in rows),
        fixture_revisions=tuple(row[2] for row in rows),
        identity_resolutions=tuple(row[3] for row in rows),
        freshness_results=tuple(row[4] for row in rows),
    )

    assert assessment.schedule_state is MatchweekScheduleState.PARTIAL
    assert assessment.scope_assessments[-1].coverage_state is ScopeCoverageState.UNKNOWN


def test_current_coverage_with_a_date_gap_remains_partial() -> None:
    bounds = CoverageBounds(
        start_utc=PREMIER_SCOPE.window_start_utc,
        end_utc="2026-09-19T23:00:00.000000+00:00",
    )
    row = _complete_scope_inputs(PREMIER_SCOPE, suffix="premier-gap", bounds=bounds)

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.PARTIAL
    assert assessment.schedule_state is MatchweekScheduleState.PARTIAL


@pytest.mark.parametrize("partition_kind", ("page", "cursor"))
def test_unaccounted_page_or_cursor_partition_keeps_scope_partial(partition_kind: str) -> None:
    row = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="premier-cursor-gap",
        required_partition_ids=(f"{partition_kind}-1", f"{partition_kind}-2"),
        accounted_partition_ids=(f"{partition_kind}-1",),
        pagination_exhausted=False,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.PARTIAL
    assert assessment.scope_assessments[0].current_coverage_evidence_ids == (row[1].evidence_id,)


def test_stale_only_scope_retains_evidence_and_does_not_count_as_current() -> None:
    row = _complete_scope_inputs(PREMIER_SCOPE, suffix="premier-stale", current=False)

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )
    premier = assessment.scope_assessments[0]

    assert premier.coverage_state is ScopeCoverageState.STALE
    assert assessment.freshness_policy_id == row[4].policy_id
    assert premier.current_coverage_evidence_ids == ()
    assert premier.stale_coverage_evidence_ids == (row[1].evidence_id,)
    assert assessment.coverage_evidence == (row[1],)
    assert assessment.freshness_results == (row[4],)
    assert premier.freshness_results == (row[4],)
    assert assessment.schedule_state is MatchweekScheduleState.STALE


def test_complementary_current_provider_ranges_combine_to_full_scope() -> None:
    split = "2026-09-19T23:00:00.000000+00:00"
    first = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="provider-friday-sunday",
        bounds=CoverageBounds(PREMIER_SCOPE.window_start_utc, split),
    )
    second = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="provider-sunday-tuesday",
        bounds=CoverageBounds(split, PREMIER_SCOPE.window_end_utc),
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(first[0], second[0]),
        coverage_evidence=(first[1], second[1]),
        fixture_revisions=(first[2],),
        identity_resolutions=(first[3],),
        freshness_results=(first[4], second[4]),
    )

    premier = assessment.scope_assessments[0]
    assert premier.coverage_state is ScopeCoverageState.COMPLETE
    assert assessment.freshness_policy_id == first[4].policy_id
    assert premier.current_coverage_evidence_ids == (
        first[1].evidence_id,
        second[1].evidence_id,
    )


def test_complementary_provider_ranges_with_different_freshness_policies_are_rejected() -> None:
    split = "2026-09-19T23:00:00.000000+00:00"
    first = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="provider-first-freshness-policy",
        bounds=CoverageBounds(PREMIER_SCOPE.window_start_utc, split),
    )
    second = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="provider-second-freshness-policy",
        bounds=CoverageBounds(split, PREMIER_SCOPE.window_end_utc),
    )
    second_freshness = CoverageFreshnessResult(
        evidence_id=second[4].evidence_id,
        policy_id="freshness-policy-v2",
        evaluated_at_utc=second[4].evaluated_at_utc,
        is_current=True,
    )

    with pytest.raises(ValueError, match="single freshness policy"):
        assess_fixture_coverage(
            scopes=SCOPES,
            provider_attempts=(first[0], second[0]),
            coverage_evidence=(first[1], second[1]),
            fixture_revisions=(first[2],),
            identity_resolutions=(first[3],),
            freshness_results=(first[4], second_freshness),
        )


def test_overlapping_duplicate_fixture_rows_do_not_change_coverage_state() -> None:
    first = _complete_scope_inputs(PREMIER_SCOPE, suffix="duplicate-source-a")
    second = _complete_scope_inputs(PREMIER_SCOPE, suffix="duplicate-source-b")
    second_revision = FixtureRevisionReference(
        scope_id=PREMIER_SCOPE.scope_id,
        fixture_id=first[2].fixture_id,
        revision_id="revision-duplicate-source-b",
        revision_digest="sha256:revision-duplicate-source-b",
        source_capture_ids=(second[1].capture_id,),
        source_assertion_ids=("assertion-duplicate-source-b",),
    )
    second_identity = FixtureIdentityResolution(
        candidate_id="candidate-duplicate-source-b",
        scope_id=PREMIER_SCOPE.scope_id,
        state=FixtureIdentityState.RESOLVED,
        canonical_fixture_id=first[2].fixture_id,
        revision_ids=(second_revision.revision_id,),
    )
    baseline = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(first[0],),
        coverage_evidence=(first[1],),
        fixture_revisions=(first[2],),
        identity_resolutions=(first[3],),
        freshness_results=(first[4],),
    )
    with_duplicate = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(first[0], second[0]),
        coverage_evidence=(first[1], second[1]),
        fixture_revisions=(first[2], second_revision),
        identity_resolutions=(first[3], second_identity),
        freshness_results=(first[4], second[4]),
    )

    assert baseline.scope_assessments[0].coverage_state is ScopeCoverageState.COMPLETE
    assert with_duplicate.scope_assessments[0].coverage_state is ScopeCoverageState.COMPLETE
    assert (
        len(
            {
                identity.canonical_fixture_id
                for identity in with_duplicate.identity_resolutions
                if identity.scope_id == PREMIER_SCOPE.scope_id
            }
        )
        == 1
    )
    assert with_duplicate.scope_assessments[0].fixture_revisions == (
        first[2],
        second_revision,
    )


@pytest.mark.parametrize(
    ("state", "http_status", "capture_id", "capture_digest"),
    [
        (ProviderAttemptState.UNAVAILABLE, None, None, None),
        (
            ProviderAttemptState.MALFORMED,
            200,
            "capture-malformed-primary",
            "sha256:capture-malformed-primary",
        ),
    ],
)
def test_failed_primary_remains_visible_when_current_fallback_proves_scope(
    state: ProviderAttemptState,
    http_status: int | None,
    capture_id: str | None,
    capture_digest: str | None,
) -> None:
    fallback = _complete_scope_inputs(PREMIER_SCOPE, suffix="fallback-full")
    primary = ProviderAttempt(
        attempt_id="attempt-primary-failed",
        scope_id=PREMIER_SCOPE.scope_id,
        provider_id="primary-feed",
        capability_id="upcoming-fixtures-v1",
        state=state,
        retrieved_at_utc="2026-09-15T11:55:00.000000+00:00",
        http_status=http_status,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(primary, fallback[0]),
        coverage_evidence=(fallback[1],),
        fixture_revisions=(fallback[2],),
        identity_resolutions=(fallback[3],),
        freshness_results=(fallback[4],),
    )

    premier = assessment.scope_assessments[0]
    assert premier.coverage_state is ScopeCoverageState.COMPLETE
    assert premier.provider_attempt_ids == (
        "attempt-fallback-full",
        "attempt-primary-failed",
    )
    assert {attempt.state for attempt in assessment.provider_attempts} >= {
        ProviderAttemptState.CAPTURED,
        state,
    }


def test_partial_fallback_does_not_replace_unavailable_primary_with_complete_coverage() -> None:
    partial_bounds = CoverageBounds(
        PREMIER_SCOPE.window_start_utc,
        "2026-09-19T23:00:00.000000+00:00",
    )
    fallback = _complete_scope_inputs(
        PREMIER_SCOPE, suffix="fallback-partial", bounds=partial_bounds
    )
    primary = ProviderAttempt(
        attempt_id="attempt-primary-unavailable",
        scope_id=PREMIER_SCOPE.scope_id,
        provider_id="primary-feed",
        capability_id="upcoming-fixtures-v1",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-15T11:55:00.000000+00:00",
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(primary, fallback[0]),
        coverage_evidence=(fallback[1],),
        fixture_revisions=(fallback[2],),
        identity_resolutions=(fallback[3],),
        freshness_results=(fallback[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.PARTIAL
    assert primary in assessment.provider_attempts


@pytest.mark.parametrize(
    ("state", "http_status", "capture_id", "capture_digest"),
    [
        (ProviderAttemptState.UNAVAILABLE, None, None, None),
        (
            ProviderAttemptState.MALFORMED,
            200,
            "capture-malformed-only",
            "sha256:capture-malformed-only",
        ),
    ],
)
def test_failed_primary_without_usable_fallback_stays_unknown(
    state: ProviderAttemptState,
    http_status: int | None,
    capture_id: str | None,
    capture_digest: str | None,
) -> None:
    failed_attempt = ProviderAttempt(
        attempt_id="attempt-malformed-only",
        scope_id=PREMIER_SCOPE.scope_id,
        provider_id="primary-feed",
        capability_id="upcoming-fixtures-v1",
        state=state,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        http_status=http_status,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(failed_attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.scope_assessments[0].provider_attempt_ids == (failed_attempt.attempt_id,)
    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN


def test_unsupported_provider_use_cannot_contribute_coverage() -> None:
    row = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="provider-not-permitted",
        permitted_for_use=False,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.scope_assessments[0].current_coverage_evidence_ids == ()


def test_empty_content_without_full_scope_evidence_is_unknown() -> None:
    row = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="empty-without-proof",
        coverage_basis=None,
        affirmatively_empty=True,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN


@pytest.mark.parametrize(
    ("provider_competition_key", "provider_season"),
    [("serie_a", "2026-27"), ("premier_league", "2025-26")],
)
def test_provider_coverage_for_wrong_competition_or_season_is_unknown(
    provider_competition_key: str,
    provider_season: str,
) -> None:
    row = _complete_scope_inputs(
        PREMIER_SCOPE,
        suffix="wrong-provider-scope",
        provider_competition_key=provider_competition_key,
        provider_season=provider_season,
    )

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=(row[0],),
        coverage_evidence=(row[1],),
        fixture_revisions=(row[2],),
        identity_resolutions=(row[3],),
        freshness_results=(row[4],),
    )

    assert assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.scope_assessments[0].current_coverage_evidence_ids == ()


def test_unresolved_conflicting_identities_block_a_complete_matchweek_and_keep_references() -> None:
    rows = tuple(_complete_scope_inputs(scope, suffix=scope.league_key) for scope in SCOPES[1:])
    evidence = _complete_scope_inputs(PREMIER_SCOPE, suffix="premier-conflict")
    first_revision = evidence[2]
    conflicting_revision = FixtureRevisionReference(
        scope_id=PREMIER_SCOPE.scope_id,
        fixture_id="fixture-different-identity",
        revision_id="revision-conflicting-identity",
        revision_digest="sha256:revision-conflicting-identity",
        source_capture_ids=("capture-conflicting-source",),
        source_assertion_ids=("assertion-conflicting-source",),
    )
    conflicting_source_attempt = ProviderAttempt(
        attempt_id="attempt-conflicting-source",
        scope_id=PREMIER_SCOPE.scope_id,
        provider_id="conflicting-feed",
        capability_id="upcoming-fixtures-v1",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-15T12:00:00.000000+00:00",
        capture_id="capture-conflicting-source",
        capture_digest="sha256:capture-conflicting-source",
    )
    blocker = FixtureIdentityResolution(
        candidate_id="candidate-conflicting-identity",
        scope_id=PREMIER_SCOPE.scope_id,
        state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
        revision_ids=(first_revision.revision_id, conflicting_revision.revision_id),
        reason_code="IDENTITY_CONFLICT",
        source_capture_ids=("capture-premier-conflict", "capture-conflicting-source"),
        source_assertion_ids=("assertion-premier-conflict", "assertion-conflicting-source"),
    )
    all_evidence = (evidence[1], *(row[1] for row in rows))
    all_attempts = (evidence[0], conflicting_source_attempt, *(row[0] for row in rows))
    all_revisions = (first_revision, conflicting_revision, *(row[2] for row in rows))
    all_freshness = (evidence[4], *(row[4] for row in rows))

    assessment = assess_fixture_coverage(
        scopes=SCOPES,
        provider_attempts=all_attempts,
        coverage_evidence=all_evidence,
        fixture_revisions=all_revisions,
        identity_resolutions=(blocker, *(row[3] for row in rows)),
        freshness_results=all_freshness,
    )

    premier = assessment.scope_assessments[0]
    assert premier.coverage_state is ScopeCoverageState.PARTIAL
    assert premier.identity_blocker_candidate_ids == (blocker.candidate_id,)
    assert premier.fixture_revisions == tuple(
        sorted((first_revision, conflicting_revision), key=lambda item: item.revision_id)
    )
    assert blocker in assessment.identity_resolutions
    assert assessment.schedule_state is MatchweekScheduleState.PARTIAL

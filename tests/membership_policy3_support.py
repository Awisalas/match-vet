"""Build exact six-scope synthetic assessments from retained test provenance."""

from dataclasses import replace
from pathlib import Path

from matchvet.active_fixture_coverage import (
    ActiveFixtureCoverageAssessment,
    active_fixture_scopes_for_matchweek,
    assess_active_fixture_coverage,
)
from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.fixture_coverage import (
    FixtureCoverageAssessment,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    SupportedFixtureCoverageAssessment,
    assess_fixture_coverage,
)
from matchvet.ingestion import (
    FixtureHistoryImporter,
    FootballDataCSVParser,
    SourceCaptureInput,
    league_by_key,
)
from matchvet.store import Store


def _six_scope_assessment(
    legacy: SupportedFixtureCoverageAssessment,
) -> ActiveFixtureCoverageAssessment:
    scopes = active_fixture_scopes_for_matchweek(
        legacy.scope_assessments[0].scope.matchweek_friday, active_scope=SUCCESSOR_SIX_SCOPE
    )
    scope_ids = {item.scope_id for item in scopes}
    evidence = tuple(item for item in legacy.coverage_evidence if item.scope_id in scope_ids)
    evidence_ids = {item.evidence_id for item in evidence}
    return assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=scopes,
        provider_attempts=tuple(v for v in legacy.provider_attempts if v.scope_id in scope_ids),
        coverage_evidence=evidence,
        fixture_revisions=tuple(v for v in legacy.fixture_revisions if v.scope_id in scope_ids),
        identity_resolutions=tuple(
            v for v in legacy.identity_resolutions if v.scope_id in scope_ids
        ),
        freshness_results=tuple(
            v for v in legacy.freshness_results if v.evidence_id in evidence_ids
        ),
    )


def _with_belgium(
    store: Store, root: Path, legacy: FixtureCoverageAssessment
) -> FixtureCoverageAssessment:
    """Retain a real earlier Belgian fixture graph in the historical assessment."""
    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\nB1,25/09/2026,09:00,Club Brugge,Anderlecht,,\n"
    )
    importer = FixtureHistoryImporter(store, private_root=root)
    capture = importer.import_dataset(
        FootballDataCSVParser().parse(
            content, league=league_by_key("belgian_pro_league"), season="2026-27"
        ),
        content,
        SourceCaptureInput(
            source_url="https://example.test/B1.csv",
            retrieved_at_utc="2026-09-16T12:00:00+00:00",
            observed_terms="Synthetic offline Belgian retention",
        ),
    )
    observation = importer.observations_for_capture(capture.source_capture_id)[0]
    assert observation.fixture_id is not None
    assert observation.revision_id is not None
    assert observation.revision_digest is not None
    scope_id = legacy.scope_assessments[-1].scope.scope_id
    return assess_fixture_coverage(
        scopes=tuple(v.scope for v in legacy.scope_assessments),
        provider_attempts=tuple(
            replace(v, capture_id=capture.source_capture_id, capture_digest=capture.source_digest)
            if v.scope_id == scope_id
            else v
            for v in legacy.provider_attempts
        ),
        coverage_evidence=tuple(
            replace(
                v,
                capture_id=capture.source_capture_id,
                capture_digest=capture.source_digest,
                affirmatively_empty=False,
            )
            if v.scope_id == scope_id
            else v
            for v in legacy.coverage_evidence
        ),
        freshness_results=legacy.freshness_results,
        fixture_revisions=(
            *legacy.fixture_revisions,
            FixtureRevisionReference(
                scope_id,
                observation.fixture_id,
                observation.revision_id,
                observation.revision_digest,
                (capture.source_capture_id,),
                observation.source_assertion_ids,
            ),
        ),
        identity_resolutions=(
            *legacy.identity_resolutions,
            FixtureIdentityResolution(
                "bel-retained",
                scope_id,
                FixtureIdentityState.RESOLVED,
                observation.fixture_id,
                (observation.revision_id,),
            ),
        ),
    )

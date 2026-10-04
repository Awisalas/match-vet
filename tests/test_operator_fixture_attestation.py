from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from matchvet.artifacts import ArtifactStore
from matchvet.fixture_coverage import (
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    FixtureScope,
    ProviderAttempt,
    ProviderAttemptState,
    ScopeCoverageState,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_codec import decode_f01, encode_f01
from matchvet.fixture_coverage_repository import (
    FixtureCoverageIntegrityError,
    FixtureCoverageRepository,
)
from matchvet.ingestion import deterministic_identifier
from matchvet.operator_fixture_attestation import (
    AttestationArtifactReference,
    CandidateAssertionFact,
    CandidateComparisonConfirmation,
    CandidateManifest,
    CandidateManifestEntry,
    CandidateManifestEntryV2,
    CandidateManifestV2,
    CandidateRevisionFact,
    OfficialPublicationReference,
    OperatorAttestationOutcome,
    OperatorComparisonConfirmations,
    ScheduleRelation,
    _canonical_json,
    _manifest_from_json,
    build_candidate_manifest,
    derive_attested_fixture_coverage,
    make_operator_coverage_attestation,
    operator_attestation_from_canonical_json,
    operator_attestation_to_canonical_json,
    policy_publications_for_scope,
)
from matchvet.provider_health import (
    CoverageState,
    FixtureCoverageAssessmentReference,
    ProviderAttemptReference,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import open_store


def _lf07_fixture_bytes(filename: str) -> bytes:
    return gzip.decompress((Path(__file__).parent / "fixtures" / filename).read_bytes())


def _base_assessment(friday: str = "2026-09-25") -> FixtureCoverageAssessment:
    scopes = fixture_scopes_for_matchweek(friday, season="2026-27")
    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-{scope.league_key}",
            scope_id=scope.scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        )
        for scope in scopes
    )
    return assess_fixture_coverage(
        scopes=scopes,
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


def _base_with_candidate(
    *,
    kickoff_local_text: str = "2026-09-25 20:00",
    resolved: bool = True,
    league_key: str = "premier_league",
    matchweek_friday: str = "2026-09-25",
    home_team_name: str = "North FC",
    away_team_name: str = "South FC",
    home_team_id: str = "team-north",
    away_team_id: str = "team-south",
    kickoff_utc: str = "2026-09-25T19:00:00.000000+00:00",
) -> tuple[
    FixtureCoverageAssessment,
    FixtureScope,
    tuple[CandidateRevisionFact, ...],
    tuple[CandidateAssertionFact, ...],
]:
    base = _base_assessment(matchweek_friday)
    scope = next(
        item.scope for item in base.scope_assessments if item.scope.league_key == league_key
    )
    capture_id = (
        "capture-premier-test" if league_key == "premier_league" else f"capture-{league_key}-test"
    )
    capture_digest = "a" * 64
    team_home = home_team_id
    team_away = away_team_id
    fixture_id = deterministic_identifier(
        "fixture", f"{scope.league_key}:{scope.season}:{team_home}:{team_away}"
    )
    assertion_ids = (
        "assertion-away",
        "assertion-home",
        "assertion-kickoff",
    )
    subject_kind = "FIXTURE" if resolved else "UNRESOLVED_FIXTURE_ROW"
    subject_key = fixture_id if resolved else "unresolved-row-1"
    assertions = tuple(
        CandidateAssertionFact(
            assertion_id=assertion_id,
            capture_id=capture_id,
            capture_digest=capture_digest,
            origin_id="origin-test",
            source_row_key="match-1",
            subject_kind=subject_kind,
            subject_key=subject_key,
            evidence_type="SCHEDULED_FIXTURE",
            predicate=predicate,
            raw_field_name=raw_field_name,
            evidence_state="OBSERVED",
            raw_value_json=json.dumps(raw_value, separators=(",", ":")),
            normalized_value_json=json.dumps(
                normalized_value, separators=(",", ":"), sort_keys=True
            ),
            unknown_reason=None,
            event_time_utc=None,
            effective_time_utc=None,
            created_at_utc="2026-09-16T12:00:00.000000+00:00",
        )
        for assertion_id, predicate, raw_field_name, raw_value, normalized_value in (
            (
                assertion_ids[0],
                "away_team",
                "team2",
                away_team_name,
                {"team_id": team_away},
            ),
            (
                assertion_ids[1],
                "home_team",
                "team1",
                home_team_name,
                {"team_id": team_home},
            ),
            (
                assertion_ids[2],
                "kickoff",
                "time",
                kickoff_local_text,
                {"kickoff_utc": kickoff_utc},
            ),
        )
    )
    attempt = ProviderAttempt(
        attempt_id=f"attempt-{scope.league_key}",
        scope_id=scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )
    attempts = tuple(
        attempt if item.scope_id == scope.scope_id else item for item in base.provider_attempts
    )
    revisions: tuple[FixtureRevisionReference, ...] = ()
    identities = (
        FixtureIdentityResolution(
            candidate_id=f"candidate-{scope.league_key}-1",
            scope_id=scope.scope_id,
            state=(
                FixtureIdentityState.RESOLVED
                if resolved
                else FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
            ),
            canonical_fixture_id=fixture_id if resolved else None,
            revision_ids=(f"revision-{scope.league_key}-1",) if resolved else (),
            reason_code=None if resolved else "TEAM_IDENTITY_UNRESOLVED",
            source_capture_ids=(capture_id,),
            source_assertion_ids=assertion_ids,
        ),
    )
    revision_facts: tuple[CandidateRevisionFact, ...] = ()
    if resolved:
        revision_payload = {
            "fixture_status": "SCHEDULED",
            "kickoff_local_text": kickoff_local_text,
            "kickoff_precision": "INSTANT",
            "kickoff_state": "OBSERVED",
            "kickoff_utc": kickoff_utc,
            "source_round": "1",
        }
        revision_digest = hashlib.sha256(
            json.dumps(
                revision_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        revision = FixtureRevisionReference(
            scope_id=scope.scope_id,
            fixture_id=fixture_id,
            revision_id=f"revision-{scope.league_key}-1",
            revision_digest=revision_digest,
            source_capture_ids=(capture_id,),
            source_assertion_ids=assertion_ids,
        )
        revisions = (revision,)
        revision_facts = (
            CandidateRevisionFact(
                reference=revision,
                home_team_id=team_home,
                away_team_id=team_away,
                kickoff_state="OBSERVED",
                kickoff_utc=kickoff_utc,
                kickoff_local_text=kickoff_local_text,
                kickoff_precision="INSTANT",
                fixture_status="SCHEDULED",
                source_round="1",
                observed_at_utc="2026-09-16T12:00:00+00:00",
            ),
        )
    assessed = assess_fixture_coverage(
        scopes=tuple(item.scope for item in base.scope_assessments),
        provider_attempts=attempts,
        coverage_evidence=(),
        fixture_revisions=revisions,
        identity_resolutions=identities,
        freshness_results=(),
    )
    return assessed, scope, revision_facts, assertions


def _candidate_attestation(
    base: FixtureCoverageAssessment,
    scope: FixtureScope,
    *,
    revision_facts: tuple[CandidateRevisionFact, ...] = (),
    assertions: tuple[CandidateAssertionFact, ...] = (),
    candidate_checks: tuple[bool, bool, bool, bool] = (True, True, True, True),
    confirmations: OperatorComparisonConfirmations | None = None,
    publications: tuple[OfficialPublicationReference, ...] | None = None,
    expected_count: int | None = None,
    verified_at_utc: str = "2026-09-17T12:00:00.000000+00:00",
) -> tuple[CandidateManifestV2, AttestationArtifactReference]:
    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=revision_facts,
        assertion_facts=assertions,
    )
    candidate_confirmations = tuple(
        CandidateComparisonConfirmation(
            candidate_id=entry.candidate_id,
            identity_matches=candidate_checks[0],
            date_matches=candidate_checks[1],
            kickoff_matches=candidate_checks[2],
            status_matches=candidate_checks[3],
        )
        for entry in manifest.entries
    )
    selected_confirmations = confirmations or OperatorComparisonConfirmations(
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
        verified_at_utc=verified_at_utc,
        publications=(
            _certification_publications_for_scope(scope) if publications is None else publications
        ),
        expected_official_fixture_count=(
            manifest.candidate_count if expected_count is None else expected_count
        ),
        candidate_confirmations=candidate_confirmations,
        confirmations=selected_confirmations,
        outcome=OperatorAttestationOutcome.CERTIFIED,
        reason=None,
    )
    content = operator_attestation_to_canonical_json(attestation).encode("utf-8")
    return manifest, AttestationArtifactReference(
        attestation=attestation,
        artifact_digest=hashlib.sha256(content).hexdigest(),
    )


def _revision_with_schedule(
    source: CandidateRevisionFact,
    *,
    revision_id: str,
    kickoff_state: str,
    kickoff_utc: str | None,
    kickoff_local_text: str | None,
    kickoff_precision: str,
    fixture_status: str = "SCHEDULED",
) -> CandidateRevisionFact:
    fact = replace(
        source,
        reference=replace(
            source.reference,
            revision_id=revision_id,
            revision_digest="0" * 64,
        ),
        kickoff_state=kickoff_state,
        kickoff_utc=kickoff_utc,
        kickoff_local_text=kickoff_local_text,
        kickoff_precision=kickoff_precision,
        fixture_status=fixture_status,
    )
    payload = {
        "fixture_status": fact.fixture_status,
        "kickoff_local_text": fact.kickoff_local_text,
        "kickoff_precision": fact.kickoff_precision,
        "kickoff_state": fact.kickoff_state,
        "kickoff_utc": fact.kickoff_utc,
        "source_round": fact.source_round,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return replace(fact, reference=replace(fact.reference, revision_digest=digest))


def _base_with_revision_facts(
    base: FixtureCoverageAssessment,
    revision_facts: tuple[CandidateRevisionFact, ...],
) -> FixtureCoverageAssessment:
    candidate_id = base.identity_resolutions[0].candidate_id
    identity = next(item for item in base.identity_resolutions if item.candidate_id == candidate_id)
    original_revision_ids = set(identity.revision_ids)
    identity = replace(
        identity,
        revision_ids=tuple(sorted(item.reference.revision_id for item in revision_facts)),
    )
    other_revisions = tuple(
        item for item in base.fixture_revisions if item.revision_id not in original_revision_ids
    )
    other_identities = tuple(
        item for item in base.identity_resolutions if item.candidate_id != candidate_id
    )
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in base.scope_assessments),
        provider_attempts=base.provider_attempts,
        coverage_evidence=base.coverage_evidence,
        fixture_revisions=(*other_revisions, *(item.reference for item in revision_facts)),
        identity_resolutions=(*other_identities, identity),
        freshness_results=base.freshness_results,
    )


def test_lf07_compatible_date_and_instant_use_v2_relation() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    original_instant = revision_facts[0]
    instant = original_instant
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-premier-date",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
    )
    facts = (date_revision, instant)
    base = _base_with_revision_facts(base, facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=assertions,
    )

    assert manifest.contract_version == "operator-fixture-candidate-manifest-v2"
    assert manifest.schema_version == 2
    entry = manifest.entries[0]
    assert isinstance(manifest, CandidateManifestV2)
    assert isinstance(entry, CandidateManifestEntryV2)
    assert entry.schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE
    assert entry.has_schedule_conflict is False
    assert entry.has_provisional_scheduling is False
    assert {item.kickoff_precision for item in entry.revision_facts} == {"DATE", "INSTANT"}


def test_lf07_manifest_versions_reject_the_other_versions_entry_type() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=revision_facts,
        assertion_facts=assertions,
    )
    v2_entry = manifest.entries[0]
    v1_entry = CandidateManifestEntry(
        candidate_id=v2_entry.candidate_id,
        scope_id=v2_entry.scope_id,
        identity_state=v2_entry.identity_state,
        canonical_fixture_id=v2_entry.canonical_fixture_id,
        revision_facts=v2_entry.revision_facts,
        assertion_facts=v2_entry.assertion_facts,
        source_capture_ids=v2_entry.source_capture_ids,
        source_assertion_ids=v2_entry.source_assertion_ids,
        reason_code=v2_entry.reason_code,
        has_schedule_conflict=v2_entry.has_schedule_conflict,
        has_provisional_scheduling=v2_entry.has_provisional_scheduling,
    )

    with pytest.raises(ValueError, match="only v1 entry values"):
        CandidateManifest(
            contract_version="operator-fixture-candidate-manifest-v1",
            schema_version=1,
            base_assessment_digest=base.digest,
            scope=manifest.scope,
            bounds=manifest.bounds,
            entries=(v2_entry,),
            candidate_count=1,
        )
    with pytest.raises(ValueError, match="only v2 entry values"):
        CandidateManifestV2(
            contract_version="operator-fixture-candidate-manifest-v2",
            schema_version=2,
            base_assessment_digest=base.digest,
            scope=manifest.scope,
            bounds=manifest.bounds,
            entries=cast(tuple[CandidateManifestEntryV2, ...], (v1_entry,)),
            candidate_count=1,
        )


@pytest.mark.parametrize("date_text", ("2026-10-09", "09/10/2026", "09/10/26"))
def test_lf07_compatible_date_uses_ingestion_date_formats(date_text: str) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate(
        matchweek_friday="2026-10-09",
        kickoff_local_text="2026-10-09 16:00",
        kickoff_utc="2026-10-09T15:00:00+00:00",
    )
    instant = revision_facts[0]
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-lf07-supported-date-format",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text=date_text,
        kickoff_precision="DATE",
    )
    facts = (instant, date_revision)
    base = _base_with_revision_facts(base, facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=assertions,
    )

    assert manifest.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE


@pytest.mark.parametrize("marker", ("tbc", "TBA", "tbd", "PROVISIONAL"))
def test_lf07_source_local_provisional_marker_prevents_certification(marker: str) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-premier-date",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
    )
    marked_assertions = tuple(
        replace(
            item,
            raw_value_json=json.dumps(f"2026-09-25 {marker}"),
            digest="",
        )
        if item.predicate == "kickoff"
        else item
        for item in assertions
    )
    facts = (instant, date_revision)
    base = _base_with_revision_facts(base, facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=marked_assertions,
    )

    entry = manifest.entries[0]
    assert entry.schedule_relation is ScheduleRelation.PROVISIONAL
    assert entry.has_schedule_conflict is False
    assert entry.has_provisional_scheduling is True
    _, attestation_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=marked_assertions,
    )
    assert attestation_reference.attestation.outcome is OperatorAttestationOutcome.REFUSED


def test_lf07_date_only_provisional_marker_remains_provisional() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    date_revision = _revision_with_schedule(
        revision_facts[0],
        revision_id="revision-premier-date-tbc",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25 TBC",
        kickoff_precision="DATE",
    )
    facts = (date_revision,)
    base = _base_with_revision_facts(base, facts)
    marked_assertions = tuple(
        replace(
            item,
            raw_value_json=json.dumps("2026-09-25 TBC"),
            digest="",
        )
        if item.predicate == "kickoff"
        else item
        for item in assertions
    )

    manifest, attestation_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=marked_assertions,
    )

    assert manifest.entries[0].schedule_relation is ScheduleRelation.PROVISIONAL
    assert attestation_reference.attestation.outcome is OperatorAttestationOutcome.REFUSED


@pytest.mark.parametrize(
    "disagreement",
    (
        "different-instant",
        "different-local-date",
        "status-postponed",
        "status-cancelled",
        "ordered-teams",
    ),
)
def test_lf07_material_schedule_disagreements_remain_conflicting(
    disagreement: str,
) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    original_instant = revision_facts[0]
    instant = original_instant
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-premier-date",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
        fixture_status=(
            "POSTPONED"
            if disagreement == "status-postponed"
            else "CANCELLED"
            if disagreement == "status-cancelled"
            else "SCHEDULED"
        ),
    )
    if disagreement == "different-local-date":
        date_revision = _revision_with_schedule(
            instant,
            revision_id="revision-premier-date",
            kickoff_state="OBSERVED",
            kickoff_utc=None,
            kickoff_local_text="2026-09-26",
            kickoff_precision="DATE",
        )
    if disagreement == "ordered-teams":
        date_revision = replace(
            date_revision,
            home_team_id=instant.away_team_id,
            away_team_id=instant.home_team_id,
        )
    selected_facts = [instant, date_revision]
    if disagreement == "different-instant":
        selected_facts.insert(
            1,
            _revision_with_schedule(
                instant,
                revision_id="revision-premier-instant-later",
                kickoff_state="OBSERVED",
                kickoff_utc="2026-09-25T20:00:00+00:00",
                kickoff_local_text="2026-09-25 21:00",
                kickoff_precision="INSTANT",
            ),
        )
    selected_revision_facts = tuple(selected_facts)
    base = _base_with_revision_facts(base, selected_revision_facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=selected_revision_facts,
        assertion_facts=assertions,
    )

    entry = manifest.entries[0]
    assert entry.schedule_relation is ScheduleRelation.CONFLICTING
    assert entry.has_schedule_conflict is True
    assert entry.has_provisional_scheduling is False
    _, attestation_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=selected_revision_facts,
        assertions=assertions,
    )
    assert attestation_reference.attestation.outcome is OperatorAttestationOutcome.REFUSED


def test_lf07_identical_instants_and_many_dates_are_order_independent() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    equivalent_instant = _revision_with_schedule(
        instant,
        revision_id="revision-premier-instant-offset",
        kickoff_state="OBSERVED",
        kickoff_utc="2026-09-25T20:00:00+01:00",
        kickoff_local_text="2026-09-25 20:00",
        kickoff_precision="INSTANT",
    )
    date_revisions = tuple(
        _revision_with_schedule(
            instant,
            revision_id=f"revision-premier-date-{index}",
            kickoff_state="OBSERVED",
            kickoff_utc=None,
            kickoff_local_text="2026-09-25",
            kickoff_precision="DATE",
        )
        for index in (1, 2)
    )
    facts = (instant, equivalent_instant, *date_revisions)
    base = _base_with_revision_facts(base, facts)

    first, first_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=assertions,
    )
    replay, replay_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=tuple(reversed(facts)),
        assertions=tuple(reversed(assertions)),
    )

    assert first.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE
    assert replay == first
    assert replay.digest == first.digest
    assert _canonical_json(replay).encode("utf-8") == _canonical_json(first).encode("utf-8")
    assert operator_attestation_to_canonical_json(
        first_reference.attestation
    ) == operator_attestation_to_canonical_json(replay_reference.attestation)


def test_lf07_real_october_9_fixture_shapes_are_compatible_offline() -> None:
    fixture_pairs = (
        ("premier_league", "Chelsea", "Bournemouth"),
        ("premier_league", "Crystal Palace", "Nottingham Forest FC"),
        ("premier_league", "Aston Villa", "Brentford"),
        ("premier_league", "Ipswich Town FC", "Fulham"),
        ("bundesliga", "Paderborn", "Stuttgart"),
        ("bundesliga", "Union Berlin", "Elversberg"),
        ("bundesliga", "Hoffenheim", "Hamburg"),
        ("bundesliga", "Augsburg", "Bayern Munich"),
        ("ligue_1", "Paris SG", "Le Mans"),
        ("ligue_1", "Lorient", "Paris FC"),
        ("ligue_1", "Monaco", "Toulouse"),
        ("serie_a", "Lazio", "AC Monza"),
    )
    relations: list[ScheduleRelation] = []
    for index, (league_key, home, away) in enumerate(fixture_pairs, start=1):
        base, scope, revision_facts, assertions = _base_with_candidate(
            league_key=league_key,
            matchweek_friday="2026-10-09",
            kickoff_local_text="2026-10-09 15:00",
            home_team_name=home,
            away_team_name=away,
            home_team_id=deterministic_identifier("team", home),
            away_team_id=deterministic_identifier("team", away),
            kickoff_utc="2026-10-09T15:00:00+00:00",
        )
        instant = revision_facts[0]
        date_revision = _revision_with_schedule(
            instant,
            revision_id=f"revision-lf07-{index:02d}-date",
            kickoff_state="OBSERVED",
            kickoff_utc=None,
            kickoff_local_text="2026-10-09",
            kickoff_precision="DATE",
        )
        facts = (instant, date_revision)
        base = _base_with_revision_facts(base, facts)
        manifest = build_candidate_manifest(
            base,
            scope.scope_id,
            revision_facts=facts,
            assertion_facts=assertions,
        )
        assert manifest.entries[0].candidate_id
        assert {item.home_team_id for item in manifest.entries[0].revision_facts} == {
            instant.home_team_id
        }
        relations.append(manifest.entries[0].schedule_relation)

    assert len(relations) == 12
    assert relations == [ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE] * 12


@pytest.mark.parametrize("failed_confirmation", (0, 1, 2, 3))
def test_lf07_compatible_precision_still_requires_four_operator_checks(
    failed_confirmation: int,
) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-premier-date-confirmation",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
    )
    facts = (instant, date_revision)
    base = _base_with_revision_facts(base, facts)
    checks = [True, True, True, True]
    checks[failed_confirmation] = False

    manifest, reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=assertions,
        candidate_checks=cast(tuple[bool, bool, bool, bool], tuple(checks)),
    )

    assert manifest.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE
    assert reference.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "disagrees" in reference.attestation.reason


def test_lf07_compatible_precision_certifies_only_with_all_explicit_checks() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    date_revision = _revision_with_schedule(
        instant,
        revision_id="revision-premier-date-certified",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
    )
    facts = (instant, date_revision)
    base = _base_with_revision_facts(base, facts)

    manifest, reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=assertions,
    )

    assert manifest.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE
    assert reference.attestation.outcome is OperatorAttestationOutcome.CERTIFIED


def test_lf07_instant_uses_league_local_date_with_termux_timezone_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zoneinfo import ZoneInfoNotFoundError

    from matchvet import ingestion

    def unavailable_zoneinfo(name: str) -> None:
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(ingestion, "ZoneInfo", unavailable_zoneinfo)
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = _revision_with_schedule(
        revision_facts[0],
        revision_id="revision-premier-local-rollover",
        kickoff_state="OBSERVED",
        kickoff_utc="2026-09-24T23:30:00+00:00",
        kickoff_local_text="2026-09-25T00:30:00+01:00",
        kickoff_precision="INSTANT",
    )
    date_revision = _revision_with_schedule(
        revision_facts[0],
        revision_id="revision-premier-local-date",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
    )
    facts = (instant, date_revision)
    base = _base_with_revision_facts(base, facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=assertions,
    )

    assert instant.kickoff_utc is not None
    assert instant.kickoff_utc[:10] == "2026-09-24"
    assert manifest.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE


def test_lf07_exact_instant_and_unknown_status_semantics() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    exact_base = _base_with_revision_facts(base, (instant,))
    exact = build_candidate_manifest(
        exact_base,
        scope.scope_id,
        revision_facts=(instant,),
        assertion_facts=assertions,
    )
    unknown_status = _revision_with_schedule(
        instant,
        revision_id="revision-premier-unknown-status",
        kickoff_state="OBSERVED",
        kickoff_utc=None,
        kickoff_local_text="2026-09-25",
        kickoff_precision="DATE",
        fixture_status="UNKNOWN",
    )
    facts = (instant, unknown_status)
    base = _base_with_revision_facts(base, facts)
    compatible = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=assertions,
    )

    assert exact.entries[0].schedule_relation is ScheduleRelation.EXACT
    assert compatible.entries[0].schedule_relation is ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE


@pytest.mark.parametrize(
    "case",
    ("date-only", "unknown-kickoff", "unknown-status"),
)
def test_lf07_unusable_kickoff_or_status_stays_provisional(case: str) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    instant = revision_facts[0]
    facts: tuple[CandidateRevisionFact, ...]
    if case == "date-only":
        facts = (
            _revision_with_schedule(
                instant,
                revision_id="revision-premier-date-only",
                kickoff_state="OBSERVED",
                kickoff_utc=None,
                kickoff_local_text="2026-09-25",
                kickoff_precision="DATE",
            ),
        )
    elif case == "unknown-kickoff":
        facts = (
            instant,
            _revision_with_schedule(
                instant,
                revision_id="revision-premier-unknown-kickoff",
                kickoff_state="UNKNOWN",
                kickoff_utc=None,
                kickoff_local_text=None,
                kickoff_precision="UNKNOWN",
            ),
        )
    else:
        facts = (
            _revision_with_schedule(
                instant,
                revision_id="revision-premier-unknown-status-instant",
                kickoff_state="OBSERVED",
                kickoff_utc=instant.kickoff_utc,
                kickoff_local_text=instant.kickoff_local_text,
                kickoff_precision="INSTANT",
                fixture_status="UNKNOWN",
            ),
            _revision_with_schedule(
                instant,
                revision_id="revision-premier-unknown-status-date",
                kickoff_state="OBSERVED",
                kickoff_utc=None,
                kickoff_local_text="2026-09-25",
                kickoff_precision="DATE",
                fixture_status="UNKNOWN",
            ),
        )
    base = _base_with_revision_facts(base, facts)

    manifest = build_candidate_manifest(
        base,
        scope.scope_id,
        revision_facts=facts,
        assertion_facts=assertions,
    )

    entry = manifest.entries[0]
    assert entry.schedule_relation is ScheduleRelation.PROVISIONAL
    assert entry.has_schedule_conflict is False
    assert entry.has_provisional_scheduling is True
    _, attestation_reference = _candidate_attestation(
        base,
        scope,
        revision_facts=facts,
        assertions=assertions,
    )
    assert attestation_reference.attestation.outcome is OperatorAttestationOutcome.REFUSED


def _certified_empty_attestations(
    base: FixtureCoverageAssessment,
) -> tuple[AttestationArtifactReference, ...]:
    confirmations = OperatorComparisonConfirmations(
        all_official_fixtures_represented=True,
        no_extra_matchvet_fixture=True,
        complete_official_publication_covers_scope=True,
        pairing_calendar_layer_checked=True,
        exact_schedule_layer_checked=True,
        latest_applicable_update_checked=True,
        complete_publication_affirms_empty_scope=True,
    )
    evidence: list[AttestationArtifactReference] = []
    for scope_assessment in base.scope_assessments:
        scope = scope_assessment.scope
        manifest = build_candidate_manifest(base, scope.scope_id, revision_facts=())
        attestation = make_operator_coverage_attestation(
            base_assessment=base,
            candidate_manifest=manifest,
            operator_id="offline-operator-1",
            verified_at_utc="2026-09-17T12:00:00.000000+00:00",
            publications=_certification_publications_for_scope(scope),
            expected_official_fixture_count=0,
            candidate_confirmations=(),
            confirmations=confirmations,
            outcome=OperatorAttestationOutcome.CERTIFIED,
            reason=None,
        )
        content = operator_attestation_to_canonical_json(attestation).encode("utf-8")
        evidence.append(
            AttestationArtifactReference(
                attestation=attestation,
                artifact_digest=hashlib.sha256(content).hexdigest(),
            )
        )
    return tuple(evidence)


def _attestations_for_candidate(
    base: FixtureCoverageAssessment,
    scope: FixtureScope,
    revision_facts: tuple[CandidateRevisionFact, ...],
    assertions: tuple[CandidateAssertionFact, ...],
) -> tuple[AttestationArtifactReference, ...]:
    return tuple(
        _candidate_attestation(
            base,
            item.scope,
            revision_facts=(revision_facts if item.scope.scope_id == scope.scope_id else ()),
            assertions=(assertions if item.scope.scope_id == scope.scope_id else ()),
        )[1]
        for item in base.scope_assessments
    )


def test_seven_explicit_attestations_derive_a_deterministic_v3_without_changing_v2() -> None:
    base = _base_assessment()
    original_bytes = encode_f01(base)
    attestations = _certified_empty_attestations(base)

    first = derive_attested_fixture_coverage(base, attestations)
    replay = derive_attested_fixture_coverage(base, attestations)
    encoded = encode_f01(first)

    assert first.contract_version == "fixture-coverage-v3-v3"
    assert first.schema_version == 3
    assert all(
        item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY
        for item in first.scope_assessments
    )
    assert first.digest == replay.digest
    assert encoded == encode_f01(replay)
    assert decode_f01(encoded) == first
    assert encode_f01(base) == original_bytes
    assert base.schedule_state.value == "UNKNOWN"
    with pytest.raises(ValueError, match="seven distinct exact scope attestations"):
        derive_attested_fixture_coverage(
            base,
            (attestations[0], attestations[0], *attestations[2:]),
        )
    with pytest.raises(ValueError, match="automatic F01 v2"):
        derive_attested_fixture_coverage(cast(FixtureCoverageAssessment, first), attestations)


def test_nonempty_candidate_produces_complete_scope_and_round_trips_attestation() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    manifest, selected = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
    )
    encoded_attestation = operator_attestation_to_canonical_json(selected.attestation)
    replayed_attestation = operator_attestation_from_canonical_json(encoded_attestation)
    assert replayed_attestation == selected.attestation
    assert manifest.digest == selected.attestation.candidate_manifest_digest

    other_scopes = tuple(
        _candidate_attestation(base, item.scope)[1] for item in base.scope_assessments[1:]
    )
    derived = derive_attested_fixture_coverage(base, (selected, *other_scopes))
    assert derived.scope_assessments[0].coverage_state is ScopeCoverageState.COMPLETE
    assert all(
        item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY
        for item in derived.scope_assessments[1:]
    )
    assert derived.schedule_state.value == "COMPLETE"
    assert derived.fixture_revisions == base.fixture_revisions
    assert derived.identity_resolutions == base.identity_resolutions


def test_candidate_comparisons_and_official_counts_fail_closed() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    _, status_mismatch = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        candidate_checks=(True, True, True, False),
    )
    assert status_mismatch.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "status" in status_mismatch.attestation.reason

    _, kickoff_mismatch = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        candidate_checks=(True, True, False, True),
    )
    assert kickoff_mismatch.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "kickoff" in kickoff_mismatch.attestation.reason

    _, date_mismatch = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        candidate_checks=(True, False, True, True),
    )
    assert date_mismatch.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "date" in date_mismatch.attestation.reason

    _, missing_official_fixture = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        expected_count=0,
    )
    assert missing_official_fixture.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "count" in missing_official_fixture.attestation.reason

    _, extra_candidate = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        expected_count=2,
    )
    assert extra_candidate.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "count" in extra_candidate.attestation.reason

    no_extra_confirmation = OperatorComparisonConfirmations(
        all_official_fixtures_represented=True,
        no_extra_matchvet_fixture=False,
        complete_official_publication_covers_scope=True,
        pairing_calendar_layer_checked=True,
        exact_schedule_layer_checked=True,
        latest_applicable_update_checked=True,
        complete_publication_affirms_empty_scope=False,
    )
    _, explicit_extra_candidate = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        confirmations=no_extra_confirmation,
        expected_count=1,
    )
    assert explicit_extra_candidate.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "extra" in explicit_extra_candidate.attestation.reason.lower()

    unapproved = replace(
        policy_publications_for_scope(scope)[0],
        publication_id="unapproved-publication",
        publisher_id="unapproved-publisher",
    )
    _, invalid_source = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        publications=(unapproved,),
    )
    assert invalid_source.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "not approved" in invalid_source.attestation.reason

    unsupported_type = replace(
        policy_publications_for_scope(scope)[0], publication_type="UNSUPPORTED_TYPE"
    )
    _, invalid_type = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        publications=(unsupported_type,),
    )
    assert invalid_type.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "not approved" in invalid_type.attestation.reason


@pytest.mark.parametrize(
    ("league_key", "publication_id", "unrelated_url"),
    (
        (
            "ligue_1",
            "ligue-1-programmation",
            "https://ligue1.com/fr/articles/l1_article_90002-unrelated-ticketing-programmation",
        ),
        (
            "liga_portugal",
            "liga-portugal-round-updates",
            "https://www.ligaportugal.pt/news/90002/unrelated-club-award-jornada",
        ),
        (
            "liga_portugal",
            "liga-portugal-round-updates",
            "https://www.ligaportugal.pt/noticias/90002/unrelated-club-award-jornada",
        ),
    ),
)
def test_unrelated_official_site_articles_are_not_approved_scheduling_sources(
    league_key: str,
    publication_id: str,
    unrelated_url: str,
) -> None:
    base = _base_assessment()
    scope = next(
        item.scope for item in base.scope_assessments if item.scope.league_key == league_key
    )
    publications = tuple(
        replace(item, official_url=unrelated_url) if item.publication_id == publication_id else item
        for item in policy_publications_for_scope(scope)
    )

    _, selected = _candidate_attestation(base, scope, publications=publications)

    assert selected.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "not approved" in selected.attestation.reason


@pytest.mark.parametrize(
    ("league_key", "publication_id", "official_url"),
    (
        (
            "ligue_1",
            "ligue-1-programmation",
            "https://ligue1.com/fr/articles/l1_article_5797-",
        ),
        (
            "liga_portugal",
            "liga-portugal-round-updates",
            "https://www.ligaportugal.pt/noticias/28531/horarios-definidos-ate-a-12.a-jornada",
        ),
    ),
)
def test_current_official_schedule_urls_are_approved_by_v2_policy(
    league_key: str, publication_id: str, official_url: str
) -> None:
    base, scope, revision_facts, assertions = _base_with_candidate(league_key=league_key)
    publications = tuple(
        replace(item, official_url=official_url) if item.publication_id == publication_id else item
        for item in policy_publications_for_scope(scope)
    )

    _, selected = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        publications=publications,
    )

    assert selected.attestation.outcome is OperatorAttestationOutcome.CERTIFIED
    assert selected.attestation.policy_snapshot.policy_version == "2"


def test_v1_policy_snapshot_remains_available_and_unchanged() -> None:
    from matchvet.operator_fixture_attestation import operator_attestation_policy_v1

    policy = operator_attestation_policy_v1()

    assert policy.policy_version == "1"
    assert (
        next(
            rule
            for rule in policy.publication_rules
            if rule.publication_id == "liga-portugal-round-updates"
        ).path_prefix
        == "/news/"
    )


def test_missing_official_reference_is_recorded_as_refusal() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    _, missing = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        publications=(),
    )
    assert missing.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "publication" in missing.attestation.reason.lower()


def test_latest_update_must_be_explicit_and_verification_is_event_bound() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    confirmations = OperatorComparisonConfirmations(
        all_official_fixtures_represented=True,
        no_extra_matchvet_fixture=True,
        complete_official_publication_covers_scope=True,
        pairing_calendar_layer_checked=True,
        exact_schedule_layer_checked=True,
        latest_applicable_update_checked=False,
        complete_publication_affirms_empty_scope=False,
    )
    _, missing_update_check = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
        confirmations=confirmations,
    )
    assert missing_update_check.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "latest applicable" in missing_update_check.attestation.reason

    with pytest.raises(ValueError, match="strictly after"):
        _candidate_attestation(
            base,
            scope,
            revision_facts=revision_facts,
            assertions=assertions,
            verified_at_utc=base.provider_attempts[0].retrieved_at_utc,
        )


def test_provisional_unresolved_and_empty_incomplete_evidence_refuse() -> None:
    provisional_base, scope, revisions, assertions = _base_with_candidate(
        kickoff_local_text="2026-09-25 TBC"
    )
    _, provisional = _candidate_attestation(
        provisional_base,
        scope,
        revision_facts=revisions,
        assertions=assertions,
    )
    assert provisional.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "Provisional or TBC MatchVet scheduling" in provisional.attestation.reason

    unresolved_base, unresolved_scope, _, unresolved_assertions = _base_with_candidate(
        resolved=False
    )
    _, unresolved = _candidate_attestation(
        unresolved_base,
        unresolved_scope,
        assertions=unresolved_assertions,
    )
    assert unresolved.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "Unresolved fixture identity" in unresolved.attestation.reason

    empty_base = _base_assessment()
    empty_scope = empty_base.scope_assessments[0].scope
    incomplete = OperatorComparisonConfirmations(
        all_official_fixtures_represented=True,
        no_extra_matchvet_fixture=True,
        complete_official_publication_covers_scope=False,
        pairing_calendar_layer_checked=True,
        exact_schedule_layer_checked=True,
        latest_applicable_update_checked=True,
        complete_publication_affirms_empty_scope=False,
    )
    _, empty = _candidate_attestation(
        empty_base,
        empty_scope,
        confirmations=incomplete,
    )
    assert empty.attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert "incomplete" in empty.attestation.reason


def test_exact_base_manifest_and_policy_bindings_cannot_be_reused() -> None:
    base, scope, revision_facts, assertions = _base_with_candidate()
    _, selected = _candidate_attestation(
        base,
        scope,
        revision_facts=revision_facts,
        assertions=assertions,
    )
    changed_attempts = (
        *base.provider_attempts[:1],
        replace(
            base.provider_attempts[1],
            retrieved_at_utc="2026-09-16T12:01:00.000000+00:00",
        ),
        *base.provider_attempts[2:],
    )
    changed_base = assess_fixture_coverage(
        scopes=tuple(item.scope for item in base.scope_assessments),
        provider_attempts=changed_attempts,
        coverage_evidence=base.coverage_evidence,
        fixture_revisions=base.fixture_revisions,
        identity_resolutions=base.identity_resolutions,
        freshness_results=base.freshness_results,
    )
    with pytest.raises(ValueError, match="changed base"):
        derive_attested_fixture_coverage(
            changed_base,
            _attestations_for_candidate(base, scope, revision_facts, assertions),
        )

    manifest = selected.attestation.candidate_manifest
    assert isinstance(manifest, CandidateManifestV2)
    entry = manifest.entries[0]
    revision = entry.revision_facts[0]
    changed_revision = replace(revision, kickoff_local_text="2026-09-25 21:00")
    changed_entry = replace(entry, revision_facts=(changed_revision,))
    changed_manifest = replace(manifest, entries=(changed_entry,), digest="")
    changed_attestation = replace(
        selected.attestation,
        candidate_manifest=changed_manifest,
        candidate_manifest_digest=changed_manifest.digest,
        digest="",
    )
    changed_reference = AttestationArtifactReference(
        attestation=changed_attestation,
        artifact_digest=selected.artifact_digest,
    )
    with pytest.raises(ValueError, match="revision facts"):
        derive_attested_fixture_coverage(
            base,
            (
                changed_reference,
                *_attestations_for_candidate(base, scope, revision_facts, assertions)[1:],
            ),
        )

    changed_policy = replace(
        selected.attestation.policy_snapshot,
        required_confirmations=(
            *selected.attestation.policy_snapshot.required_confirmations,
            "changed-policy-input",
        ),
        digest="",
    )
    changed_policy_attestation = replace(
        selected.attestation,
        policy_snapshot=changed_policy,
        policy_digest=changed_policy.digest,
        digest="",
    )
    with pytest.raises(ValueError, match="policy snapshot"):
        derive_attested_fixture_coverage(
            base,
            (
                AttestationArtifactReference(changed_policy_attestation, selected.artifact_digest),
                *_attestations_for_candidate(base, scope, revision_facts, assertions)[1:],
            ),
        )


def test_codec_rejects_unsupported_or_mismatched_f01_versions() -> None:
    payload = json.loads(encode_f01(_base_assessment()))
    payload["contract_version"] = "fixture-coverage-v3-v3"
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    with pytest.raises(FixtureCoveragePayloadError, match="unsupported F01 versions"):
        decode_f01(encoded)

    payload["contract_version"] = "unknown-fixture-coverage"
    payload["schema_version"] = 99
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    with pytest.raises(FixtureCoveragePayloadError, match="unsupported F01 versions"):
        decode_f01(encoded)


def test_f03_persists_and_replays_v3_with_protected_attestation_artifacts(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        assert store.status.schema_version == 14
        repository.persist(base)
        references = tuple(
            repository.persist_attestation(item.attestation)
            for item in _certified_empty_attestations(base)
        )
        derived = derive_attested_fixture_coverage(base, references)

        assert repository.persist(derived) == derived.digest
        assert repository.get(base.digest) == base
        assert repository.get(derived.digest) == derived
        for reference in references:
            assert (
                repository.get_attestation_artifact(reference.artifact_digest)
                == reference.attestation
            )
        artifact_rows = (
            store._connection_for_repository()
            .execute("SELECT digest, media_type FROM artifacts ORDER BY digest")
            .fetchall()
        )
        assert len(artifact_rows) == 7
        assert all(
            row[1] == "application/vnd.matchvet.operator-fixture-attestation-v2+json"
            for row in artifact_rows
        )
        assert {ArtifactStore(store).read_artifact(str(row[0])) for row in artifact_rows} == {
            operator_attestation_to_canonical_json(item.attestation).encode("utf-8")
            for item in references
        }
        assert all(
            ArtifactStore(store).verify_artifact(str(row[0])).retention_class == "PROTECTED"
            for row in artifact_rows
        )


def test_lf07_v1_manifest_and_attestation_keep_original_canonical_bytes() -> None:
    manifest_bytes = _lf07_fixture_bytes("lf07_v1_conflicting_candidate_manifest.json.gz")
    manifest_root = json.loads(manifest_bytes)
    manifest = _manifest_from_json(manifest_root)
    assert isinstance(manifest, CandidateManifest)
    assert manifest.contract_version == "operator-fixture-candidate-manifest-v1"
    assert manifest.schema_version == 1
    assert manifest.digest == (
        "sha256:a7aed56dba25428a23be8196c9b3028b50c3fb61344409947a4d5b0e0458ba29"
    )
    assert _canonical_json(manifest).encode("utf-8") == manifest_bytes
    assert manifest.entries[0].has_schedule_conflict is True
    assert manifest.entries[0].has_provisional_scheduling is True

    attestation_bytes = _lf07_fixture_bytes("lf07_v1_conflicting_attestation.json.gz")
    attestation = operator_attestation_from_canonical_json(attestation_bytes.decode("utf-8"))
    assert attestation.contract_version == "operator-fixture-attestation-v1"
    assert attestation.schema_version == 1
    assert isinstance(attestation.candidate_manifest, CandidateManifest)
    assert attestation.candidate_manifest.digest == manifest.digest
    assert attestation.outcome is OperatorAttestationOutcome.REFUSED
    assert attestation.digest == (
        "sha256:3c03a73963844e09364a50fe59bc7d7fff70a30d6158379a17fe2d3e236484ba"
    )
    assert operator_attestation_to_canonical_json(attestation).encode("utf-8") == attestation_bytes


def test_lf07_v1_attestations_and_f01_v3_replay_exactly_in_isolated_store(
    tmp_path: Path,
) -> None:
    golden = json.loads(_lf07_fixture_bytes("lf07_v1_empty_attestations.json.gz"))
    base = _base_assessment()
    assert base.digest == golden["base_assessment_digest"]
    old_references_by_scope: dict[str, AttestationArtifactReference] = {}
    for scope_id, encoded in golden["attestations"].items():
        attestation = operator_attestation_from_canonical_json(encoded)
        assert attestation.contract_version == "operator-fixture-attestation-v1"
        assert attestation.schema_version == 1
        assert isinstance(attestation.candidate_manifest, CandidateManifest)
        assert operator_attestation_to_canonical_json(attestation) == encoded
        old_references_by_scope[scope_id] = AttestationArtifactReference(
            attestation=attestation,
            artifact_digest=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    expected_scope_order = tuple(item.scope.scope_id for item in base.scope_assessments)
    old_references = tuple(old_references_by_scope[item] for item in expected_scope_order)
    old_v3_bytes = _lf07_fixture_bytes("lf07_v1_v3_empty_assessment.json.gz")
    decoded_v3 = decode_f01(old_v3_bytes.decode("utf-8"))
    assert decoded_v3.digest == golden["v3_assessment_digest"]
    assert encode_f01(decoded_v3).encode("utf-8") == old_v3_bytes

    private_root = tmp_path / "lf07-v1-private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        assert store.status.schema_version == 14
        assert store.status.applied_migrations == tuple(range(1, 15))
        repository.persist(base)
        persisted_references = tuple(
            repository.persist_attestation(item.attestation) for item in old_references
        )
        for item in persisted_references:
            replay = repository.get_attestation_artifact(item.artifact_digest)
            assert operator_attestation_to_canonical_json(
                replay
            ) == operator_attestation_to_canonical_json(item.attestation)
            assert replay.contract_version == "operator-fixture-attestation-v1"
            assert isinstance(replay.candidate_manifest, CandidateManifest)

        derived = derive_attested_fixture_coverage(base, persisted_references)
        assert encode_f01(derived).encode("utf-8") == old_v3_bytes
        assert repository.persist(derived) == derived.digest
        assert repository.get(derived.digest) == decoded_v3

        artifact_media_types = {
            str(row[0])
            for row in store._connection_for_repository()
            .execute("SELECT DISTINCT media_type FROM artifacts")
            .fetchall()
        }
        assert artifact_media_types == {
            "application/vnd.matchvet.operator-fixture-attestation-v1+json"
        }


def test_f03_rejects_v3_with_missing_attestation_artifact(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    references = _certified_empty_attestations(base)
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        repository.persist(base)
        with pytest.raises(FixtureCoverageIntegrityError, match="artifact"):
            repository.persist(derive_attested_fixture_coverage(base, references))


def test_f03_requires_a_persisted_exact_base_before_attestation_artifact_publish(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    attestation = _certified_empty_attestations(base)[0].attestation
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        with pytest.raises(FixtureCoverageIntegrityError, match="persisted automatic v2"):
            repository.persist_attestation(attestation)


def test_f03_recomputes_candidate_manifest_before_attestation_artifact_publish(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    valid = _certified_empty_attestations(base)[0].attestation
    manifest = valid.candidate_manifest
    assert isinstance(manifest, CandidateManifestV2)
    forged_entry = CandidateManifestEntryV2(
        candidate_id="operator-inserted-candidate",
        scope_id=manifest.scope.scope_id,
        identity_state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
        canonical_fixture_id=None,
        revision_facts=(),
        assertion_facts=(),
        source_capture_ids=(),
        source_assertion_ids=(),
        reason_code="OPERATOR_INSERTED",
        has_schedule_conflict=False,
        has_provisional_scheduling=True,
        schedule_relation=ScheduleRelation.PROVISIONAL,
    )
    forged_manifest = replace(
        manifest,
        entries=(forged_entry,),
        candidate_count=1,
        digest="",
    )
    forged = replace(
        valid,
        candidate_manifest=forged_manifest,
        candidate_manifest_digest=forged_manifest.digest,
        observed_candidate_count=1,
        digest="",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        repository.persist(base)
        with pytest.raises(FixtureCoverageIntegrityError, match="candidate manifest"):
            repository.persist_attestation(forged)


@pytest.mark.parametrize("damage", ("missing", "corrupt", "wrong-kind"))
def test_f03_rejects_missing_corrupt_or_wrong_kind_attestation_artifact(
    tmp_path: Path, damage: str
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    attestations = _certified_empty_attestations(base)
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        repository.persist(base)
        references: list[AttestationArtifactReference] = []
        for index, item in enumerate(attestations):
            if damage == "wrong-kind" and index == 0:
                content = operator_attestation_to_canonical_json(item.attestation).encode("utf-8")
                record = ArtifactStore(store).publish_artifact(
                    content, media_type="application/json", retention_class="PROTECTED"
                )
                references.append(AttestationArtifactReference(item.attestation, record.digest))
            else:
                references.append(repository.persist_attestation(item.attestation))
        assessment = derive_attested_fixture_coverage(base, tuple(references))

        if damage == "wrong-kind":
            with pytest.raises(FixtureCoverageIntegrityError, match="kind"):
                repository.persist(assessment)
            return

        repository.persist(assessment)
        damaged_digest = references[0].artifact_digest
        record = ArtifactStore(store).verify_artifact(damaged_digest)
        artifact_path = private_root / record.relative_path
        if damage == "missing":
            artifact_path.unlink()
        else:
            artifact_path.write_bytes(b"not canonical MatchVet attestation bytes")
        with pytest.raises(FixtureCoverageIntegrityError, match="attestation artifact"):
            repository.get(assessment.digest)


def test_f05_accepts_independent_v3_and_uses_actual_attempts_only(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    base = _base_assessment()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        f01 = FixtureCoverageRepository(store)
        f01.persist(base)
        attestations = tuple(
            f01.persist_attestation(item.attestation)
            for item in _certified_empty_attestations(base)
        )
        assessment = derive_attested_fixture_coverage(base, attestations)
        f01.persist(assessment)

        assert not isinstance(assessment, FixtureCoverageAssessment)
        v2_records = build_provider_health_records(base)
        assert len(v2_records) == len(base.provider_attempts) == 7

        records = build_provider_health_records(assessment)
        assert len(records) == len(base.provider_attempts) == 7
        assert {
            reference.attempt_id
            for item in records
            for reference in item.provenance
            if isinstance(reference, ProviderAttemptReference)
        } == {item.attempt_id for item in assessment.provider_attempts}
        assert all(item.coverage.state is CoverageState.UNKNOWN for item in records)
        assert all(
            any(
                isinstance(reference, FixtureCoverageAssessmentReference)
                and reference.assessment_digest == assessment.digest
                and reference.contract_version == "fixture-coverage-v3-v3"
                for reference in item.provenance
            )
            for item in records
        )
        assert ProviderHealthRepository(store).persist_many(records)
        replayed = ProviderHealthRepository(store).list_for_assessment(assessment.digest)
        assert {item.digest for item in replayed} == {item.digest for item in records}

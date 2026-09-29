from __future__ import annotations

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
    CandidateRevisionFact,
    OfficialPublicationReference,
    OperatorAttestationOutcome,
    OperatorComparisonConfirmations,
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


def _base_assessment() -> FixtureCoverageAssessment:
    scopes = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")
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
) -> tuple[
    FixtureCoverageAssessment,
    FixtureScope,
    tuple[CandidateRevisionFact, ...],
    tuple[CandidateAssertionFact, ...],
]:
    base = _base_assessment()
    scope = base.scope_assessments[0].scope
    capture_id = "capture-premier-test"
    capture_digest = "a" * 64
    team_home = "team-north"
    team_away = "team-south"
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
                "South FC",
                {"team_id": team_away},
            ),
            (
                assertion_ids[1],
                "home_team",
                "team1",
                "North FC",
                {"team_id": team_home},
            ),
            (
                assertion_ids[2],
                "kickoff",
                "time",
                kickoff_local_text,
                {"kickoff_utc": "2026-09-25T19:00:00.000000+00:00"},
            ),
        )
    )
    attempt = ProviderAttempt(
        attempt_id="attempt-premier-league",
        scope_id=scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )
    attempts = (attempt, *base.provider_attempts[1:])
    revisions: tuple[FixtureRevisionReference, ...] = ()
    identities = (
        FixtureIdentityResolution(
            candidate_id="candidate-premier-1",
            scope_id=scope.scope_id,
            state=(
                FixtureIdentityState.RESOLVED
                if resolved
                else FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
            ),
            canonical_fixture_id=fixture_id if resolved else None,
            revision_ids=("revision-premier-1",) if resolved else (),
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
            "kickoff_utc": "2026-09-25T19:00:00.000000+00:00",
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
            revision_id="revision-premier-1",
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
                kickoff_utc="2026-09-25T19:00:00.000000+00:00",
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
) -> tuple[CandidateManifest, AttestationArtifactReference]:
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
    assert "Provisional or TBC" in provisional.attestation.reason

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
        assert store.status.schema_version == 13
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
            row[1] == "application/vnd.matchvet.operator-fixture-attestation-v1+json"
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
    forged_entry = CandidateManifestEntry(
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
        has_provisional_scheduling=False,
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

"""LF14 behavior at the exact F06 persistence and replay interfaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from test_matchweek_membership import (
    _assessment_with_higher_authority_revision,
    _persist_attested_assessment,
    _persistable_schedule_assessment,
)

from matchvet.fixture_coverage import (
    FixtureCoverageAssessment,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    SupportedFixtureCoverageAssessment,
    assess_fixture_coverage,
)
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.ingestion import (
    TARGET_LEAGUES,
    FixtureHistoryImporter,
    FootballDataCSVParser,
    SourceCaptureInput,
    deterministic_identifier,
    league_by_key,
)
from matchvet.matchweek_membership import (
    MatchweekMembershipError,
    MatchweekMembershipFreeze,
    canonical_json,
    decision_payload,
    freeze_digest,
    freeze_payload,
    membership_digest,
    membership_set_digest,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import CanonicalIdentifier, Store, open_store


def test_exact_conflict_projection_accepts_ac_subset_of_abc_history(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        original = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        _assessment_with_higher_authority_revision(
            store, tmp_path, original, kickoff="13:00", cache_key="B", attempt_id="B"
        )
        selected = _assessment_with_higher_authority_revision(
            store, tmp_path, original, kickoff="14:00", cache_key="C", attempt_id="C"
        )
        FixtureCoverageRepository(store).persist(selected)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(selected))
        repository = MatchweekMembershipRepository(store)
        frozen = repository.freeze_exact(
            "2026-27", "2026-09-25", selected.digest, "matchvet:matchweek-membership", "2"
        )
        assert len(frozen.memberships) == 1
        assert frozen.memberships[0].controlling_revision.kickoff_utc == (
            "2026-09-25T13:00:00+00:00"
        )
        conflict = frozen.memberships[0].conflicts[0]
        assert len(conflict.assertion_ids) == 2
        assert repository.get_by_id(frozen.freeze_id) == frozen
        assert (
            repository.freeze_exact(
                "2026-27", "2026-09-25", selected.digest, "matchvet:matchweek-membership", "2"
            )
            == frozen
        )
        _with_capture(store, tmp_path, selected, time="15:00", key="D")
        assert repository.get_by_id(frozen.freeze_id) == frozen


def _with_capture(
    store: Store,
    tmp_path: Path,
    original: FixtureCoverageAssessment,
    *,
    home: str = "Start United",
    away: str = "Start City",
    time: str = "12:00",
    status: str | None = None,
    key: str = "extra",
    retrieved_at: str = "2026-09-17T12:00:00+00:00",
) -> FixtureCoverageAssessment:
    league = league_by_key("premier_league")
    content = (
        f"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\nE0,25/09/2026,{time},{home},{away},,\n"
    ).encode()
    dataset = FootballDataCSVParser().parse(content, league=league, season="2026-27")
    if status is not None:
        dataset = replace(
            dataset,
            rows=tuple(replace(row, explicit_fixture_status=status) for row in dataset.rows),
        )
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    capture = importer.import_dataset(
        dataset,
        content,
        SourceCaptureInput(
            source_url=f"https://example.test/{key}.csv",
            retrieved_at_utc=retrieved_at,
            observed_terms="Synthetic offline fixture",
            cache_key=key,
        ),
    )
    observation = importer.observations_for_capture(capture.source_capture_id)[0]
    assert observation.fixture_id == original.fixture_revisions[0].fixture_id
    assert observation.revision_id is not None and observation.revision_digest is not None
    reference = FixtureRevisionReference(
        scope_id=original.fixture_revisions[0].scope_id,
        fixture_id=observation.fixture_id,
        revision_id=observation.revision_id,
        revision_digest=observation.revision_digest,
        source_capture_ids=(capture.source_capture_id,),
        source_assertion_ids=observation.source_assertion_ids,
    )
    references = {item.revision_id: item for item in original.fixture_revisions}
    prior = references.get(reference.revision_id)
    if prior:
        reference = replace(
            reference,
            source_capture_ids=tuple(
                sorted(set((*prior.source_capture_ids, *reference.source_capture_ids)))
            ),
            source_assertion_ids=tuple(
                sorted(set((*prior.source_assertion_ids, *reference.source_assertion_ids)))
            ),
        )
    references[reference.revision_id] = reference
    attempt = replace(
        next(item for item in original.provider_attempts if item.scope_id == reference.scope_id),
        attempt_id=key,
        capture_id=capture.source_capture_id,
        capture_digest=capture.source_digest,
        retrieved_at_utc=datetime.fromisoformat(retrieved_at).isoformat(timespec="microseconds"),
    )
    return assess_fixture_coverage(
        scopes=tuple(item.scope for item in original.scope_assessments),
        provider_attempts=(*original.provider_attempts, attempt),
        coverage_evidence=original.coverage_evidence,
        fixture_revisions=tuple(references.values()),
        identity_resolutions=(
            *original.identity_resolutions,
            FixtureIdentityResolution(
                candidate_id=key,
                scope_id=reference.scope_id,
                state=FixtureIdentityState.RESOLVED,
                canonical_fixture_id=reference.fixture_id,
                revision_ids=(reference.revision_id,),
            ),
        ),
        freshness_results=original.freshness_results,
    )


def _freeze(
    store: Store, assessment: SupportedFixtureCoverageAssessment
) -> MatchweekMembershipFreeze:
    FixtureCoverageRepository(store).persist(assessment)
    ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
    return MatchweekMembershipRepository(store).freeze_exact(
        "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "2"
    )


def test_equivalent_source_spellings_preserve_raw_provenance_and_canonical_identity(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        league = league_by_key("premier_league")
        seed = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/09/2026,Arsenal,Chelsea,1,0\n"
        importer.import_dataset(
            FootballDataCSVParser().parse(seed, league=league, season="2026-27"),
            seed,
            SourceCaptureInput(
                source_url="https://example.test/seed.csv",
                retrieved_at_utc="2026-09-16T12:00:00+00:00",
                observed_terms="Synthetic seed",
            ),
        )
        original = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Arsenal FC", "Chelsea FC"),)
        )
        selected = _with_capture(store, tmp_path, original, home="Arsenal", away="Chelsea")
        before = importer.source_assertions()
        frozen = _freeze(store, selected)
        assert len(frozen.memberships) == 1
        assert frozen.memberships[0].conflicts == ()
        assert importer.source_assertions() == before
        assert MatchweekMembershipRepository(store).get_by_id(frozen.freeze_id) == frozen


def test_scheduled_and_confirmed_are_one_membership_status_class(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        original = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        scheduled = _with_capture(store, tmp_path, original, status="SCHEDULED", key="scheduled")
        confirmed = _with_capture(store, tmp_path, scheduled, status="CONFIRMED", key="confirmed")
        frozen = _freeze(store, confirmed)
        assert frozen.memberships[0].decision.value == "INCLUDED"
        assert frozen.memberships[0].conflicts == ()
        assert MatchweekMembershipRepository(store).get_by_digest(frozen.freeze_digest) == frozen


def test_same_tier_date_and_instant_are_compatible_and_use_exact_kickoff(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        original = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        dated = _with_capture(store, tmp_path, original, time="", key="date")
        exact = _with_capture(store, tmp_path, dated, time="12:00", key="instant")
        frozen = _freeze(store, exact)
        assert frozen.memberships[0].controlling_revision.kickoff_precision == "INSTANT"
        assert frozen.memberships[0].conflicts == ()
        assert MatchweekMembershipRepository(store).get_by_id(frozen.freeze_id) == frozen


@pytest.mark.parametrize("valid_digest", (False, True))
@pytest.mark.parametrize("policy_version", ("1", "2"))
@pytest.mark.parametrize("mismatch", ("kickoff", "status"))
def test_supported_revision_requires_content_digest_and_assertion_coherence(
    tmp_path: Path, valid_digest: bool, policy_version: str, mismatch: str
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        reference = base.fixture_revisions[0]
        payload = {
            "fixture_status": "POSTPONED" if mismatch == "status" else "SCHEDULED",
            "kickoff_local_text": "2026-09-25T12:00:00+01:00",
            "kickoff_precision": "INSTANT",
            "kickoff_state": "OBSERVED",
            "kickoff_utc": "2026-09-25T11:00:00+00:00"
            if mismatch == "status"
            else "2026-09-28T20:00:00+00:00",
            "source_round": None,
        }
        digest = (
            hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if valid_digest
            else "0" * 64
        )
        revision_id = deterministic_identifier(
            "fixture_revision", f"{reference.fixture_id}:{digest}"
        )
        with store.transaction() as tx:
            tx.add_identifier_if_missing(CanonicalIdentifier("fixture_revision", revision_id))
            tx.execute(
                """INSERT INTO fixture_revisions
                SELECT ?,fixture_id,revision_id,?,kickoff_state,?, ?,kickoff_precision,
                ?,source_round,observed_at_utc,source_capture_id,
                source_assertion_ids_json,created_at_utc
                FROM fixture_revisions WHERE revision_id=?""",
                (
                    revision_id,
                    digest,
                    payload["kickoff_utc"],
                    payload["kickoff_local_text"],
                    payload["fixture_status"],
                    reference.revision_id,
                ),
            )
            for assertion_id in reference.source_assertion_ids:
                tx.execute(
                    "INSERT INTO fixture_revision_assertions VALUES (?, ?)",
                    (revision_id, assertion_id),
                )
        bad = assess_fixture_coverage(
            scopes=tuple(item.scope for item in base.scope_assessments),
            provider_attempts=base.provider_attempts,
            coverage_evidence=base.coverage_evidence,
            fixture_revisions=(
                replace(reference, revision_id=revision_id, revision_digest=digest),
            ),
            identity_resolutions=(
                replace(base.identity_resolutions[0], revision_ids=(revision_id,)),
            ),
            freshness_results=base.freshness_results,
        )
        with pytest.raises(MatchweekMembershipError) as refusal:
            FixtureCoverageRepository(store).persist(bad)
            ProviderHealthRepository(store).persist_many(build_provider_health_records(bad))
            MatchweekMembershipRepository(store).freeze_exact(
                "2026-27", "2026-09-25", bad.digest, "matchvet:matchweek-membership", policy_version
            )
        assert refusal.value.reason_code == "REFERENCE_CORRUPT"


def test_candidate_id_change_alone_is_not_identity_resolution(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        frozen = _freeze(store, base)
        later = assess_fixture_coverage(
            scopes=tuple(item.scope for item in base.scope_assessments),
            provider_attempts=base.provider_attempts,
            coverage_evidence=base.coverage_evidence,
            fixture_revisions=base.fixture_revisions,
            identity_resolutions=(
                replace(base.identity_resolutions[0], candidate_id="new-row-id"),
            ),
            freshness_results=base.freshness_results,
        )
        FixtureCoverageRepository(store).persist(later)
        repository = MatchweekMembershipRepository(store)
        observation = repository.append_observation(frozen.freeze_id, later.digest)
        assert observation.changes == ()
        assert repository.append_observation(frozen.freeze_id, later.digest) == observation


@pytest.mark.parametrize("disagreement", ("kickoff", "status"))
def test_genuine_controlling_tier_disagreement_fails_closed(
    tmp_path: Path, disagreement: str
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        first = _with_capture(store, tmp_path, base, status="SCHEDULED", key="first")
        second = _with_capture(
            store,
            tmp_path,
            first,
            key="contradiction",
            time="13:00" if disagreement == "kickoff" else "12:00",
            status="POSTPONED" if disagreement == "status" else "SCHEDULED",
        )
        with pytest.raises(MatchweekMembershipError) as refusal:
            _freeze(store, second)
        assert refusal.value.reason_code == "MEMBERSHIP_CONFLICT"


@pytest.mark.parametrize("inject_failure", (False, True))
def test_all_seven_66_decision_freeze_is_atomic_and_idempotent(
    tmp_path: Path, inject_failure: bool
) -> None:
    from test_operator_fixture_observation import _official_scheduling_input, _seed_league_teams

    from matchvet.matchweek_membership_repository import MatchweekMembershipPersistenceError
    from matchvet.operator_fixture_observation import OperatorFixtureObservationRepository

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        rows = {
            league.key: tuple(
                ("2026-09-25", "20:00", f"{league.key} Home {index}", f"{league.key} Away {index}")
                for index in range(count)
            )
            for league, count in zip(TARGET_LEAGUES, (10, 10, 10, 9, 9, 9, 9), strict=True)
        }
        belgian_rows = rows.pop("belgian_pro_league")
        baseline = _persistable_schedule_assessment(store, tmp_path, (), rows_by_league=rows)
        _seed_league_teams(
            store,
            tuple(name for _, _, home, away in belgian_rows for name in (home, away)),
            "belgian_pro_league",
        )
        manual_repository = OperatorFixtureObservationRepository(store, private_root=tmp_path)
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        references = list(baseline.fixture_revisions)
        identities = list(baseline.identity_resolutions)
        scope = next(
            item.scope
            for item in baseline.scope_assessments
            if item.scope.league_key == "belgian_pro_league"
        )
        for index, (_, _, home, away) in enumerate(belgian_rows):
            recorded = manual_repository.record(
                _official_scheduling_input(
                    "belgian_pro_league",
                    home=home,
                    away=away,
                    friday="2026-09-25",
                    kickoff="2026-09-25T20:00:00+02:00",
                    publication_date="2026-09-16",
                )
            )
            observation = importer.observations_for_capture(recorded.capture_id)[0]
            assert observation.revision_digest is not None
            references.append(
                FixtureRevisionReference(
                    scope.scope_id,
                    recorded.fixture_id,
                    recorded.revision_id,
                    observation.revision_digest,
                    (recorded.capture_id,),
                    observation.source_assertion_ids,
                )
            )
            identities.append(
                FixtureIdentityResolution(
                    f"belgian-manual-{index}",
                    scope.scope_id,
                    FixtureIdentityState.RESOLVED,
                    recorded.fixture_id,
                    (recorded.revision_id,),
                )
            )
            replayed = manual_repository.get(recorded.artifact_digest)
            assert replayed.observation == recorded.observation
            assert (replayed.capture_id, replayed.fixture_id, replayed.revision_id) == (
                recorded.capture_id,
                recorded.fixture_id,
                recorded.revision_id,
            )
        base = assess_fixture_coverage(
            scopes=tuple(item.scope for item in baseline.scope_assessments),
            provider_attempts=baseline.provider_attempts,
            coverage_evidence=tuple(
                replace(item, affirmatively_empty=False)
                if item.scope_id == scope.scope_id
                else item
                for item in baseline.coverage_evidence
            ),
            fixture_revisions=tuple(references),
            identity_resolutions=tuple(identities),
            freshness_results=baseline.freshness_results,
        )
        coverage_repository = FixtureCoverageRepository(store)
        coverage_repository.persist(base)
        assessment = _persist_attested_assessment(store, coverage_repository, base)
        repository = MatchweekMembershipRepository(store)
        if inject_failure:
            with store.transaction() as tx:
                tx.execute("""CREATE TRIGGER lf14_fail BEFORE INSERT
                ON v2_matchweek_membership_health_refs
                BEGIN SELECT RAISE(ABORT, 'LF14 child-write failure'); END""")
            with pytest.raises(MatchweekMembershipPersistenceError):
                _freeze(store, assessment)
            assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()
            assert (
                store._connection_for_repository()
                .execute("SELECT count(*) FROM v2_matchweek_membership_decisions")
                .fetchone()[0]
                == 0
            )
            with store.transaction() as tx:
                tx.execute("DROP TRIGGER lf14_fail")
        frozen = _freeze(store, assessment)
        assert len(frozen.scopes) == 7
        assert len(frozen.memberships) == 66
        assert len({item.fixture_id for item in frozen.memberships}) == 66
        assert all(item.decision.value == "INCLUDED" for item in frozen.memberships)
        assert repository.get_by_id(frozen.freeze_id) == frozen
        assert _freeze(store, assessment) == frozen


@pytest.mark.parametrize("omit", ("integrity", "conflict", "legacy_integrity"))
def test_policy2_replay_rejects_omitted_integrity_evidence(tmp_path: Path, omit: str) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        selected = _with_capture(store, tmp_path, base, time="13:00")
        frozen = _freeze(store, selected)
        semantic = frozen
        if omit == "legacy_integrity":
            frozen = MatchweekMembershipRepository(store).freeze_exact(
                "2026-27", "2026-09-25", selected.digest, "matchvet:matchweek-membership", "1"
            )
        original = frozen.memberships[0]
        if omit == "integrity":
            revisions = tuple(
                replace(item, integrity=None) for item in original.evaluated_revisions
            )
            changed = replace(
                original,
                evaluated_revisions=revisions,
                controlling_revision=replace(original.controlling_revision, integrity=None),
            )
        elif omit == "conflict":
            changed = replace(original, conflicts=(), reason_codes=(original.reason_code,))
        else:
            evidence = {
                item.revision_id: item.integrity
                for item in semantic.memberships[0].evaluated_revisions
            }
            changed = replace(
                original,
                evaluated_revisions=tuple(
                    replace(item, integrity=evidence[item.revision_id])
                    for item in original.evaluated_revisions
                ),
                controlling_revision=replace(
                    original.controlling_revision,
                    integrity=evidence[original.controlling_revision_id],
                ),
            )
        changed = replace(changed, membership_digest=membership_digest(changed))
        forged = replace(
            frozen, memberships=(changed,), membership_set_digest=membership_set_digest((changed,))
        )
        forged = replace(forged, freeze_digest=freeze_digest(forged))
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER v2_matchweek_membership_freezes_no_update")
            tx.execute("DROP TRIGGER v2_matchweek_membership_decisions_no_update")
            tx.execute(
                "UPDATE v2_matchweek_membership_freezes SET freeze_json=?,freeze_digest=?,"
                "membership_set_digest=? WHERE freeze_id=?",
                (
                    canonical_json(freeze_payload(forged, include_digest=True)),
                    forged.freeze_digest,
                    forged.membership_set_digest,
                    frozen.freeze_id,
                ),
            )
            tx.execute(
                "UPDATE v2_matchweek_membership_decisions SET decision_json=?,"
                "membership_digest=? WHERE membership_id=?",
                (
                    canonical_json(decision_payload(changed, include_digest=True)),
                    changed.membership_digest,
                    changed.membership_id,
                ),
            )
        with pytest.raises(MatchweekMembershipError):
            MatchweekMembershipRepository(store).get_by_id(frozen.freeze_id)


def test_different_canonical_team_assertion_is_rejected(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER source_assertions_no_update")
            tx.execute(
                "UPDATE source_assertions SET normalized_value_json=? "
                "WHERE predicate='home_team' AND subject_key=?",
                ('"Start City"', base.fixture_revisions[0].fixture_id),
            )
        with pytest.raises(MatchweekMembershipError) as refusal:
            _freeze(store, base)
        assert refusal.value.reason_code == "REFERENCE_CORRUPT"


@pytest.mark.parametrize("policy_version", ("1", "2"))
def test_conflict_history_must_cover_every_selected_assertion(
    tmp_path: Path, policy_version: str
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        old = _with_capture(store, tmp_path, base, time="13:00", key="older-B")
        selected = _with_capture(
            store,
            tmp_path,
            old,
            time="13:00",
            key="latest-B",
            retrieved_at="2026-09-18T12:00:00+00:00",
        )
        capture_id = next(
            item.capture_id for item in selected.provider_attempts if item.attempt_id == "latest-B"
        )
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER conflict_assertions_no_delete")
            tx.execute(
                "DELETE FROM conflict_assertions WHERE assertion_id IN "
                "(SELECT assertion_id FROM source_assertions "
                "WHERE capture_id=? AND predicate='kickoff')",
                (capture_id,),
            )
        with pytest.raises(MatchweekMembershipError) as refusal:
            FixtureCoverageRepository(store).persist(selected)
            ProviderHealthRepository(store).persist_many(build_provider_health_records(selected))
            MatchweekMembershipRepository(store).freeze_exact(
                "2026-27",
                "2026-09-25",
                selected.digest,
                "matchvet:matchweek-membership",
                policy_version,
            )
        assert refusal.value.reason_code == "REFERENCE_CORRUPT"


def test_selected_revision_cannot_omit_explicit_status_assertion(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        selected = _with_capture(store, tmp_path, base, status="SCHEDULED")
        status_ids = {
            item.assertion_id
            for item in FixtureHistoryImporter(store, private_root=tmp_path).source_assertions()
            if item.predicate == "fixture_status"
        }
        missing = assess_fixture_coverage(
            scopes=tuple(item.scope for item in selected.scope_assessments),
            provider_attempts=selected.provider_attempts,
            coverage_evidence=selected.coverage_evidence,
            identity_resolutions=selected.identity_resolutions,
            freshness_results=selected.freshness_results,
            fixture_revisions=tuple(
                replace(
                    item,
                    source_assertion_ids=tuple(
                        key for key in item.source_assertion_ids if key not in status_ids
                    ),
                )
                for item in selected.fixture_revisions
            ),
        )
        with pytest.raises(MatchweekMembershipError) as refusal:
            _freeze(store, missing)
        assert refusal.value.reason_code == "REFERENCE_CORRUPT"


def test_legacy_date_assertion_timestamps_remain_immutable_and_compatible(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "", "Start United", "Start City"),)
        )
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER source_assertions_no_update")
            tx.execute(
                "UPDATE source_assertions SET event_time_utc='2026-09-25',"
                "effective_time_utc='2026-09-25' WHERE predicate='kickoff'",
            )
        exact = _with_capture(store, tmp_path, base)
        repository = FixtureCoverageRepository(store)
        repository.persist(exact)
        manifest = repository.build_candidate_manifest(exact, exact.fixture_revisions[0].scope_id)
        assert manifest.candidate_count == 1
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        before = importer.source_assertions()
        frozen = _freeze(store, exact)
        assert frozen.memberships[0].controlling_revision.kickoff_precision == "INSTANT"
        assert MatchweekMembershipRepository(store).get_by_id(frozen.freeze_id) == frozen
        assert importer.source_assertions() == before


@pytest.mark.parametrize("missing_value", (False, True))
def test_explicit_status_requires_observed_value(tmp_path: Path, missing_value: bool) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        base = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        selected = _with_capture(store, tmp_path, base, status="SCHEDULED")
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER source_assertions_no_update")
            if missing_value:
                tx.execute(
                    "UPDATE source_assertions SET normalized_value_json=NULL "
                    "WHERE predicate='fixture_status'"
                )
            else:
                tx.execute(
                    "UPDATE source_assertions SET evidence_state='UNKNOWN',"
                    "unknown_reason='SOURCE_MISSING_FIELD' WHERE predicate='fixture_status'"
                )
        with pytest.raises(MatchweekMembershipError) as refusal:
            _freeze(store, selected)
        assert refusal.value.reason_code == "REFERENCE_CORRUPT"

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_matchweek_membership import _persistable_schedule_assessment

from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import (
    CutoffPolicy,
    MatchEvidenceCutoffError,
    MatchEvidenceCutoffRepository,
)
from matchvet.matchweek_membership import canonical_json, freeze_payload
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import Store, open_store


def test_cutoffs_persist_independently_retry_and_reopen_without_changing_freeze(
    tmp_path: Path,
) -> None:
    database = tmp_path / "matchvet.sqlite3"
    with open_store(database, private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (
                ("2026-09-25", "20:00", "Friday United", "Friday City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
                ("2026-09-29", "20:00", "Excluded United", "Excluded City"),
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freezes = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC)
        )
        freeze = freezes.freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        original = canonical_json(freeze_payload(freeze, include_digest=True))
        repo = MatchEvidenceCutoffRepository(store)
        # Test configuration only; no production timing default.
        policy = repo.persist_policy(CutoffPolicy("test-cutoff", "experiment-1", 3600))
        cutoffs = repo.persist_for_freeze(freeze.freeze_id, policy)
        assert len(cutoffs) == 2
        assert tuple(item.digest for item in cutoffs) == (
            "sha256:e4cb5077d9c5ff8413337ea0ba72862312f65772bc42240be7054a2ea7c3e12b",
            "sha256:3b824fe15ce964de1a2b17c94f701360480b899a1a48095f996acca90067b2f5",
        )
        assert {c.cutoff_at_utc for c in cutoffs} == {
            "2026-09-25T18:00:00.000000+00:00",
            "2026-09-28T18:00:00.000000+00:00",
        }
        assert repo.persist_for_freeze(freeze.freeze_id, policy) == cutoffs
        for cutoff in cutoffs:
            member = next(m for m in freeze.memberships if m.membership_id == cutoff.membership_id)
            assert cutoff.fixture_revision_ref == member.controlling_revision_id
            assert cutoff.fixture_revision_digest == member.controlling_revision_digest
            assert cutoff.freeze_digest == freeze.freeze_digest
            assert cutoff.membership_digest == member.membership_digest
            assert cutoff.policy_digest == policy
            assert repo.get_by_id(cutoff.cutoff_id) == cutoff
        replayed = freezes.get_by_id(freeze.freeze_id)
        assert replayed is not None
        assert canonical_json(freeze_payload(replayed, include_digest=True)) == original
    with open_store(database, private_root=tmp_path) as store:
        repo = MatchEvidenceCutoffRepository(store)
        assert repo.replay_for_freeze(freeze.freeze_id, policy) == cutoffs
        assert repo.persist_for_freeze(freeze.freeze_id, policy) == cutoffs


def test_matchweek_rule_uses_earliest_exact_included_kickoff_for_every_member(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (("2026-09-25", "20:00", "Friday United", "Friday City"),
             ("2026-09-28", "20:00", "Monday United", "Monday City")),
            rows_by_league={
                "premier_league": (("2026-09-28", "20:00", "Monday United", "Monday City"),),
                "serie_a": (("2026-09-25", "20:00", "Friday United", "Friday City"),),
            },
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy(
            "matchweek-cutoff", "1", 21600,
            rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
        ))
        inclusions = [m for m in freeze.memberships if m.decision.value == "INCLUDED"]
        monday = next(
            m
            for m in inclusions
            if m.controlling_revision.kickoff_utc.startswith("2026-09-28")
        )
        single = repo.persist_exact(freeze.freeze_id, monday.membership_id, policy)
        all_cutoffs = repo.persist_for_freeze(freeze.freeze_id, policy)
        assert len(all_cutoffs) == 2
        assert single.cutoff_at_utc == "2026-09-25T12:00:00.000000+00:00"
        assert {item.cutoff_at_utc for item in all_cutoffs} == {single.cutoff_at_utc}
        assert repo.replay(single.cutoff_id) == single
        changed_policy = repo.persist_policy(CutoffPolicy(
            "matchweek-cutoff", "2", 3600,
            rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
        ))
        changed = repo.persist_exact(freeze.freeze_id, monday.membership_id, changed_policy)
        assert changed.cutoff_id != single.cutoff_id
        assert changed.cutoff_at_utc == "2026-09-25T17:00:00.000000+00:00"


def test_corrected_policy_refuses_freeze_created_after_matchweek_started(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-28", "20:00", "Home United", "Away City"),)
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 26, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy(
            "matchweek-cutoff", "1", 21600,
            rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
        ))
        with pytest.raises(MatchEvidenceCutoffError):
            repo.persist_exact(
                freeze.freeze_id,
                next(
                    m.membership_id
                    for m in freeze.memberships
                    if m.decision.value == "INCLUDED"
                ),
                policy,
            )


def test_corrected_policy_refuses_empty_included_set(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (),
            rows_by_league={
                "premier_league": (),
                "serie_a": (),
                "la_liga": (),
                "bundesliga": (),
                "ligue_1": (),
                "liga_portugal": (),
                "belgian_pro_league": (),
            },
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy(
            "matchweek-cutoff", "1", 21600,
            rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
        ))
        with pytest.raises(MatchEvidenceCutoffError, match="INCLUDED"):
            repo.persist_for_freeze(freeze.freeze_id, policy)


def _freeze(store: Store, tmp_path: Path) -> str:
    assessment = _persistable_schedule_assessment(
        store, tmp_path, (("2026-09-25", "20:00", "Home United", "Away City"),)
    )
    FixtureCoverageRepository(store).persist(assessment)
    ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
    return (
        MatchweekMembershipRepository(store)
        .freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        .freeze_id
    )


def test_changed_policy_preserves_old_cutoff_and_evidence_boundary(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy("test-cutoff", "1", 7200))
        old = repo.persist_for_freeze(freeze_id, policy)[0]
        changed = repo.persist_policy(CutoffPolicy("test-cutoff", "2", 3600))
        new = repo.persist_for_freeze(freeze_id, changed)[0]
        assert old.cutoff_id != new.cutoff_id
        assert old.digest != new.digest
        assert old.cutoff_at_utc == "2026-09-25T17:00:00.000000+00:00"
        assert new.cutoff_at_utc == "2026-09-25T18:00:00.000000+00:00"
        assert repo.replay(old.cutoff_id) == old
        assert not repo.evidence_is_pre_cutoff(
            old.cutoff_id,
            published_at_utc="2026-09-25T17:30:00+00:00",
            retrieved_at_utc="2026-09-25T17:30:00+00:00",
        )
        assert not repo.evidence_is_pre_cutoff(
            old.cutoff_id,
            published_at_utc="2026-09-25T16:00:00+00:00",
            retrieved_at_utc="2026-09-25T17:30:00+00:00",
        )
        assert repo.evidence_is_pre_cutoff(
            old.cutoff_id,
            published_at_utc="2026-09-25T17:00:00+00:00",
            retrieved_at_utc="2026-09-25T17:00:00+00:00",
        )
        assert not repo.evidence_is_pre_cutoff(
            old.cutoff_id, published_at_utc=None, retrieved_at_utc="2026-09-25T16:00:00+00:00"
        )
        with pytest.raises(MatchEvidenceCutoffError, match="UTC"):
            repo.evidence_is_pre_cutoff(
                old.cutoff_id,
                published_at_utc="2026-09-25T16:00:00",
                retrieved_at_utc="2026-09-25T16:00:00+00:00",
            )


def test_missing_configuration_references_and_incomplete_replay_refuse(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        repo = MatchEvidenceCutoffRepository(store)
        pending = repo.persist_policy(CutoffPolicy("test-cutoff", "unset", None))
        with pytest.raises(MatchEvidenceCutoffError) as error:
            repo.persist_for_freeze(freeze_id, pending)
        assert error.value.code == "MV-F07-POLICY-UNCONFIGURED"
        policy = repo.persist_policy(CutoffPolicy("test-cutoff", "1", 3600))
        for action in (
            lambda: repo.persist_for_freeze("missing-freeze", policy),
            lambda: repo.persist_for_freeze(freeze_id, "0" * 64),
            lambda: repo.persist_exact(freeze_id, "wrong-membership", policy),
            lambda: repo.replay_for_freeze(freeze_id, policy),
        ):
            with pytest.raises(MatchEvidenceCutoffError):
                action()
        with pytest.raises(MatchEvidenceCutoffError):
            CutoffPolicy("test", "1", 3600, schema_version=2)
        with pytest.raises(MatchEvidenceCutoffError):
            CutoffPolicy("test", "1", 3600, rule="UNSUPPORTED")


def test_changed_fixture_revision_requires_new_freeze_and_retains_old_cutoff(
    tmp_path: Path,
) -> None:
    import json
    from dataclasses import replace

    from matchvet.fixture_coverage import FixtureRevisionReference, assess_fixture_coverage
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        OpenFootballJSONParser,
        SourceCaptureInput,
        league_by_key,
    )

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        freezes = MatchweekMembershipRepository(store)
        frozen = freezes.get_by_id(freeze_id)
        assert frozen is not None
        base = FixtureCoverageRepository(store).get(frozen.assessment_digest)
        assert base is not None
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy("test", "1", 3600))
        old = repo.persist_for_freeze(freeze_id, policy)[0]
        original_bytes = canonical_json(freeze_payload(frozen, include_digest=True))
        league = league_by_key("premier_league")
        content = json.dumps(
            {
                "matches": [
                    {
                        "date": "2026-09-25",
                        "time": "21:00",
                        "team1": "Home United",
                        "team2": "Away City",
                        "score": {},
                    }
                ]
            }
        ).encode()
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        imported = importer.import_dataset(
            OpenFootballJSONParser().parse(content, league=league, season="2026-27"),
            content,
            SourceCaptureInput(
                source_url="https://example.test/corrected.json",
                retrieved_at_utc="2026-09-17T12:00:00+00:00",
                observed_terms="CC0",
                cache_key="f07-corrected",
            ),
        )
        observation = importer.observations_for_capture(imported.source_capture_id)[0]
        assert observation.fixture_id == old.fixture_id
        assert observation.revision_id is not None and observation.revision_digest is not None
        assert repo.replay(old.cutoff_id) == old
        new_reference = FixtureRevisionReference(
            scope_id=base.fixture_revisions[0].scope_id,
            fixture_id=old.fixture_id,
            revision_id=observation.revision_id,
            revision_digest=observation.revision_digest,
            source_capture_ids=(imported.source_capture_id,),
            source_assertion_ids=observation.source_assertion_ids,
        )
        revised = assess_fixture_coverage(
            scopes=tuple(item.scope for item in base.scope_assessments),
            provider_attempts=tuple(
                replace(
                    a,
                    attempt_id="f07-corrected-attempt",
                    capture_id=imported.source_capture_id,
                    capture_digest=imported.source_digest,
                    retrieved_at_utc="2026-09-17T12:00:00.000000+00:00",
                )
                if a.scope_id == new_reference.scope_id
                else a
                for a in base.provider_attempts
            ),
            coverage_evidence=tuple(
                replace(
                    e,
                    attempt_id="f07-corrected-attempt",
                    capture_id=imported.source_capture_id,
                    capture_digest=imported.source_digest,
                )
                if e.scope_id == new_reference.scope_id
                else e
                for e in base.coverage_evidence
            ),
            fixture_revisions=(new_reference,),
            identity_resolutions=tuple(
                replace(i, revision_ids=(observation.revision_id,))
                for i in base.identity_resolutions
            ),
            freshness_results=base.freshness_results,
        )
        FixtureCoverageRepository(store).persist(revised)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(revised))
        successor = freezes.freeze_exact(
            "2026-27", "2026-09-25", revised.digest, "matchvet:matchweek-membership", "1"
        )
        new = repo.persist_for_freeze(successor.freeze_id, policy)[0]
        assert new.cutoff_id != old.cutoff_id
        assert new.fixture_revision_ref == observation.revision_id
        assert new.cutoff_at_utc == "2026-09-25T19:00:00.000000+00:00"
        assert repo.replay(old.cutoff_id) == old
        replayed = freezes.get_by_id(freeze_id)
        assert replayed is not None
        assert canonical_json(freeze_payload(replayed, include_digest=True)) == original_bytes


def test_corrupt_cutoff_payloads_refuse_at_public_replay(tmp_path: Path) -> None:
    import json
    from dataclasses import asdict

    from matchvet.artifacts import ArtifactStore
    from matchvet.match_evidence_cutoff import CUTOFF_MEDIA_TYPE

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = repo.persist_for_freeze(freeze_id, policy)[0]
        for key, bad in (
            ("freeze_id", []),
            ("membership_digest", "wrong"),
            ("fixture_revision_ref", "wrong"),
            ("policy_digest", "0" * 64),
            ("cutoff_at_utc", "2026-09-25T19:00:00+00:00"),
            ("schema_version", 2),
        ):
            payload = asdict(cutoff)
            payload[key] = bad
            artifact = ArtifactStore(store).publish_artifact(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                CUTOFF_MEDIA_TYPE,
            )
            with pytest.raises(MatchEvidenceCutoffError):
                repo.replay("f07:" + artifact.digest)


def test_corrupt_or_missing_durable_references_refuse_replay_and_retry(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze_id = _freeze(store, tmp_path)
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = repo.persist_for_freeze(freeze_id, policy)[0]
        metadata = store.artifact_metadata(policy)
        assert metadata is not None
        policy_path = tmp_path / metadata.relative_path
        original = policy_path.read_bytes()
        policy_path.unlink()
        with pytest.raises(MatchEvidenceCutoffError):
            repo.replay(cutoff.cutoff_id)
        policy_path.write_bytes(b"corrupt")
        with pytest.raises(MatchEvidenceCutoffError):
            repo.persist_for_freeze(freeze_id, policy)
        policy_path.write_bytes(original)
        assert repo.replay(cutoff.cutoff_id) == cutoff
        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER fixture_revisions_no_update")
            transaction.execute(
                "UPDATE fixture_revisions SET fixture_status = 'CANCELLED' WHERE revision_id = ?",
                (cutoff.fixture_revision_ref,),
            )
        with pytest.raises(MatchEvidenceCutoffError) as error:
            repo.replay(cutoff.cutoff_id)
        assert error.value.code == "MV-F07-REFERENCE-CORRUPT"
        with pytest.raises(MatchEvidenceCutoffError):
            repo.persist_for_freeze(freeze_id, policy)

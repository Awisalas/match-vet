"""Six-scope F06/F07 admission beside immutable historical membership."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from membership_policy3_support import _six_scope_assessment
from test_matchweek_membership import (
    _persistable_empty_assessment,
    _persistable_schedule_assessment,
)

from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.fixture_coverage import FixtureCoverageAssessment, ScopeCoverageState
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.matchweek_membership import (
    MatchweekMembershipError,
    canonical_json,
    freeze_from_canonical_json,
    freeze_payload,
    policy_snapshot,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import Store, open_store


def _persist(store: Store, assessment: FixtureCoverageAssessment) -> None:
    FixtureCoverageRepository(store).persist(assessment)
    ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))


def _repository(store: Store) -> MatchweekMembershipRepository:
    return MatchweekMembershipRepository(store, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC))


def test_policy3_exact_six_freeze_and_semantic_roundtrip(tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        assessment = _six_scope_assessment(legacy)
        _persist(store, assessment)
        repository = _repository(store)
        frozen = repository.freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
        )
        assert tuple(item.league_key for item in frozen.scopes) == SUCCESSOR_SIX_SCOPE.league_keys
        assert frozen.contract_version == "matchweek-membership-freeze-v2"
        assert frozen.payload_version == 1
        assert len(frozen.memberships) == 1
        assert frozen.memberships[0].controlling_revision.integrity is not None
        assert repository.get_by_id(frozen.freeze_id) == frozen
        assert repository.persist_exact(frozen) == frozen
        assert (
            freeze_from_canonical_json(canonical_json(freeze_payload(frozen, include_digest=True)))
            == frozen
        )


def test_policy3_binds_exact_contract_and_historical_policy_hashes() -> None:
    import json

    document = json.loads(policy_snapshot("matchvet:matchweek-membership", "3").canonical_json)
    assert document["active_scope"] == {
        "contract_id": "matchvet-active-scope-v2",
        "version": 2,
        "season": "2026-27",
        "league_keys": [
            "premier_league",
            "serie_a",
            "la_liga",
            "bundesliga",
            "ligue_1",
            "liga_portugal",
        ],
        "digest": "sha256:47e48cdf62e8452b9ec869bb99771d975972d6b9514d48e62866bca8f29dbb54",
    }
    assert document["fixture_coverage"] == {
        "contract_version": "fixture-coverage-v4-v4",
        "schema_version": 4,
    }
    assert (
        policy_snapshot("matchvet:matchweek-membership", "1").digest
        == "sha256:05c155a0dd2477d0ee4b4dbc4953d5f5b0c63eff56ff1f53243ae50298a532ef"
    )
    assert (
        policy_snapshot("matchvet:matchweek-membership", "2").digest
        == "sha256:7d3ff80e0e53e57afe13a48ff8ac25395560639cb28758ea9b8ca4a337901b3a"
    )
    assert (
        document["integrity"]
        == json.loads(policy_snapshot("matchvet:matchweek-membership", "2").canonical_json)[
            "integrity"
        ]
    )
    with pytest.raises(MatchweekMembershipError):
        policy_snapshot("matchvet:matchweek-membership", "4")


@pytest.mark.parametrize("version,six", (("1", True), ("2", True), ("3", False)))
def test_incompatible_f01_policy_pair_refuses(tmp_path: Path, version: str, six: bool) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_empty_assessment(store, tmp_path)
        assessment = _six_scope_assessment(legacy) if six else legacy
        _persist(store, assessment)
        with pytest.raises(MatchweekMembershipError, match="contract pair"):
            _repository(store).freeze_exact(
                "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", version
            )
        assert _repository(store).list_for_matchweek("2026-27", "2026-09-25") == ()


@pytest.mark.parametrize("mode", ("confirmed_empty", "unknown", "partial", "stale"))
def test_six_completeness_gate(tmp_path: Path, mode: str) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_empty_assessment(
            store, tmp_path, coverage_mode="confirmed_empty" if mode == "unknown" else mode
        )
        if mode == "unknown":
            legacy = replace(
                legacy,
                coverage_evidence=(),
                freshness_results=(),
                freshness_policy_id=None,
                digest="",
            )
        assessment = _six_scope_assessment(legacy)
        FixtureCoverageRepository(store).persist(assessment)
        if mode == "confirmed_empty":
            ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
            frozen = _repository(store).freeze_exact(
                "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
            )
            assert len(frozen.scopes) == 6
            assert all(v.coverage_state == "CONFIRMED_EMPTY" for v in frozen.scopes)
            assert frozen.memberships == ()
        else:
            with pytest.raises(MatchweekMembershipError) as refusal:
                _repository(store).freeze_exact(
                    "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
                )
            assert refusal.value.reason_code == "ASSESSMENT_INCOMPLETE"


def test_all_six_complete_and_one_unknown_scope_refusal(tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _six_scope_assessment(
            _persistable_schedule_assessment(
                store,
                tmp_path,
                (),
                rows_by_league={
                    key: (("2026-09-25", "20:00", "Home United", "Away City"),)
                    for key in SUCCESSOR_SIX_SCOPE.league_keys
                },
            )
        )
        assert all(
            v.coverage_state is ScopeCoverageState.COMPLETE for v in assessment.scope_assessments
        )
        _persist(store, assessment)
        frozen = _repository(store).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
        )
        assert len(frozen.memberships) == 6
        from matchvet.active_fixture_coverage import assess_active_fixture_coverage

        missing = assess_active_fixture_coverage(
            active_scope=SUCCESSOR_SIX_SCOPE,
            scopes=tuple(v.scope for v in assessment.scope_assessments),
            provider_attempts=assessment.provider_attempts,
            coverage_evidence=assessment.coverage_evidence[:-1],
            freshness_results=tuple(
                v
                for v in assessment.freshness_results
                if v.evidence_id != assessment.coverage_evidence[-1].evidence_id
            ),
            fixture_revisions=assessment.fixture_revisions,
            identity_resolutions=assessment.identity_resolutions,
        )
        assert any(
            v.coverage_state is ScopeCoverageState.UNKNOWN for v in missing.scope_assessments
        )
        FixtureCoverageRepository(store).persist(missing)
        with pytest.raises(MatchweekMembershipError):
            _repository(store).freeze_exact(
                "2026-27", "2026-09-25", missing.digest, "matchvet:matchweek-membership", "3"
            )


def test_observation_attaches_only_to_exact_population_and_keeps_freeze(tmp_path: Path) -> None:
    from test_lf14 import _with_capture

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        initial = _six_scope_assessment(legacy)
        _persist(store, legacy)
        _persist(store, initial)
        repo = _repository(store)
        seven = repo.freeze_exact(
            "2026-27", "2026-09-25", legacy.digest, "matchvet:matchweek-membership", "2"
        )
        six = repo.freeze_exact(
            "2026-27", "2026-09-25", initial.digest, "matchvet:matchweek-membership", "3"
        )
        original_bytes = canonical_json(six.to_payload())
        later_seven = _with_capture(store, tmp_path, legacy, time="13:00")
        later_six = _six_scope_assessment(later_seven)
        _persist(store, later_seven)
        _persist(store, later_six)
        for freeze, assessment in ((six, later_seven), (seven, later_six)):
            with pytest.raises(MatchweekMembershipError):
                repo.append_observation(freeze.freeze_id, assessment.digest)
        observation = repo.append_observation(six.freeze_id, later_six.digest)
        assert observation.freeze_id == six.freeze_id
        assert observation.assessment_digest == later_six.digest
        assert len(observation.scopes) == 6
        assert observation.changes
        assert repo.list_observations(six.freeze_id) == (observation,)
        replay = repo.get_by_id(six.freeze_id)
        assert replay is not None
        assert canonical_json(replay.to_payload()) == original_bytes


@pytest.mark.parametrize("transition", ("reassigned", "ambiguous", "unresolved", "scope_changed"))
def test_policy3_refuses_unsupported_stable_candidate_transitions(
    tmp_path: Path, transition: str
) -> None:
    from matchvet.fixture_coverage import FixtureIdentityState

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_schedule_assessment(
            store,
            tmp_path,
            (),
            rows_by_league={
                "premier_league": (("2026-09-25", "20:00", "Home A", "Away A"),),
                "serie_a": (("2026-09-26", "20:00", "Home B", "Away B"),),
            },
        )
        initial = _six_scope_assessment(legacy)
        _persist(store, initial)
        repo = _repository(store)
        frozen = repo.freeze_exact(
            "2026-27", "2026-09-25", initial.digest, "matchvet:matchweek-membership", "3"
        )
        left, right = initial.identity_resolutions
        if transition == "ambiguous":
            later = replace(
                initial,
                identity_resolutions=(left, replace(right, candidate_id=left.candidate_id)),
                digest="",
            )
        elif transition == "unresolved":
            # An unresolved later candidate is allowed by F01; it cannot masquerade
            # as an explicit resolution of this already frozen stable identity.
            later = replace(
                initial,
                identity_resolutions=(
                    replace(
                        left,
                        state=FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY,
                        canonical_fixture_id=None,
                        reason_code="IDENTITY_UNRESOLVED",
                    ),
                    right,
                ),
                scope_assessments=tuple(
                    replace(v, identity_blocker_candidate_ids=(left.candidate_id,))
                    if v.scope.scope_id == left.scope_id
                    else v
                    for v in initial.scope_assessments
                ),
                digest="",
            )
        elif transition == "scope_changed":
            later = replace(
                initial,
                identity_resolutions=(
                    replace(left, candidate_id=right.candidate_id),
                    replace(right, candidate_id=left.candidate_id),
                ),
                digest="",
            )
        else:
            # Same scope, different canonical fixtures: preserve valid F01 graphs.
            another = _persistable_schedule_assessment(
                store,
                tmp_path,
                (
                    ("2026-09-25", "20:00", "Home C", "Away C"),
                    ("2026-09-26", "20:00", "Home D", "Away D"),
                ),
            )
            another = _six_scope_assessment(another)
            later = replace(
                another,
                identity_resolutions=(
                    replace(another.identity_resolutions[0], candidate_id=left.candidate_id),
                    another.identity_resolutions[1],
                ),
                digest="",
            )
        FixtureCoverageRepository(store).persist(later)
        with pytest.raises(MatchweekMembershipError):
            repo.append_observation(frozen.freeze_id, later.digest)
        assert repo.list_observations(frozen.freeze_id) == ()


def test_historical_freeze_goldens_stay_exact_after_policy3(tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        _persist(store, legacy)
        repo = _repository(store)
        old = tuple(
            repo.freeze_exact(
                "2026-27", "2026-09-25", legacy.digest, "matchvet:matchweek-membership", v
            )
            for v in ("1", "2")
        )
        # Recorded on the pre-#99 implementation, with this explicit fixed clock.
        assert tuple(v.freeze_digest for v in old) == (
            "sha256:d1f5ac7db87204c6cd8707f246d5cc1e50841117375af2122ffaf982c1786f8d",
            "sha256:de80c799ec58b5c84f62b119935a549dcacc47111ae4eaef49a1a60196cb2a2b",
        )
        encoded = tuple(canonical_json(v.to_payload()) for v in old)
        six = _six_scope_assessment(legacy)
        _persist(store, six)
        repo.freeze_exact("2026-27", "2026-09-25", six.digest, "matchvet:matchweek-membership", "3")
        for frozen, expected in zip(old, encoded, strict=True):
            replay = repo.get_by_id(frozen.freeze_id)
            assert replay is not None
            assert canonical_json(replay.to_payload()) == expected


def test_mixed_store_cutoffs_integrity_and_backup_restore(tmp_path: Path) -> None:
    import sqlite3

    from membership_policy3_support import _with_belgium
    from test_lf14 import _with_capture
    from test_t17 import _safe_resource_observation

    from matchvet.artifacts import ArtifactStore
    from matchvet.match_evidence_cutoff import (
        CutoffPolicy,
        MatchEvidenceCutoffError,
        MatchEvidenceCutoffRepository,
    )
    from matchvet.store import InspectionStatus, inspect_store
    from matchvet.t17 import backup_store, restore_backup, verify_backup

    root = tmp_path / "private"
    database = root / "store.sqlite3"
    with open_store(database, private_root=root) as store:
        legacy = _persistable_schedule_assessment(
            store,
            root,
            (
                ("2026-09-25", "20:00", "Start United", "Start City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
                ("2026-09-24", "20:00", "Excluded United", "Excluded City"),
            ),
        )
        legacy = _with_belgium(store, root, legacy)
        _persist(store, legacy)
        repo = _repository(store)
        old = tuple(
            repo.freeze_exact(
                "2026-27", "2026-09-25", legacy.digest, "matchvet:matchweek-membership", version
            )
            for version in ("1", "2")
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        timing = cutoffs.persist_policy(
            CutoffPolicy(
                "common-cutoff",
                "1",
                21600,
                rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
            )
        )
        old_cutoffs = tuple(cutoffs.persist_for_freeze(f.freeze_id, timing) for f in old)
        assert all(
            {c.cutoff_at_utc for c in group} == {"2026-09-25T01:00:00.000000+00:00"}
            for group in old_cutoffs
        )
        old_bytes = tuple(canonical_json(f.to_payload()) for f in old)
        old_cutoff_bytes = tuple(tuple(c.to_bytes() for c in group) for group in old_cutoffs)
        six = _six_scope_assessment(legacy)
        _persist(store, six)
        successor = repo.freeze_exact(
            "2026-27", "2026-09-25", six.digest, "matchvet:matchweek-membership", "3"
        )
        new_cutoffs = cutoffs.persist_for_freeze(successor.freeze_id, timing)
        assert len(new_cutoffs) == 2
        assert {c.cutoff_at_utc for c in new_cutoffs} == {"2026-09-25T13:00:00.000000+00:00"}
        assert all(
            c.freeze_id == successor.freeze_id and c.freeze_digest == successor.freeze_digest
            for c in new_cutoffs
        )
        assert all("belgian" not in m.scope_id for m in successor.memberships)
        assert (
            len(successor.memberships) == 3
        )  # The earlier excluded Thursday fixture cannot control T.
        assert any("belgian" in m.scope_id for m in old[0].memberships)
        later = _six_scope_assessment(_with_capture(store, root, legacy, time="21:00"))
        FixtureCoverageRepository(store).persist(later)
        observation = repo.append_observation(successor.freeze_id, later.digest)
        assert all("belgian" not in c.scope_id for c in observation.changes)
        for rule, lead in (
            ("KICKOFF_MINUS_LEAD_TIME", 21600),
            ("MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME", 3600),
            ("MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME", None),
        ):
            invalid = cutoffs.persist_policy(
                CutoffPolicy("invalid-for-six", str(lead) + rule, lead, rule=rule)
            )
            with pytest.raises(MatchEvidenceCutoffError):
                cutoffs.persist_for_freeze(successor.freeze_id, invalid)
        assert len(repo.list_for_matchweek("2026-27", "2026-09-25")) == 3
        for frozen, expected in zip(old, old_bytes, strict=True):
            replay = repo.get_by_id(frozen.freeze_id)
            assert replay is not None
            assert canonical_json(replay.to_payload()) == expected
        assert (
            tuple(
                tuple(c.to_bytes() for c in cutoffs.replay_for_freeze(f.freeze_id, timing))
                for f in old
            )
            == old_cutoff_bytes
        )
        connection = store._connection_for_repository()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as tx:
            tx.execute(
                "UPDATE v2_matchweek_membership_freezes SET created_at_utc='changed' "
                "WHERE freeze_id=?",
                (successor.freeze_id,),
            )
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as tx:
            tx.execute(
                "DELETE FROM v2_matchweek_membership_observations WHERE observation_id=?",
                (observation.observation_id,),
            )
        artifacts = ArtifactStore(store)
        assert artifacts.inspect().missing == artifacts.inspect().corrupt == ()
        for cutoff in new_cutoffs:
            artifact = store.artifact_metadata(cutoff.digest.removeprefix("sha256:"))
            assert artifact is not None and artifact.retention_class == "PROTECTED"
    assert inspect_store(database, private_root=root).status is InspectionStatus.HEALTHY
    bundle = tmp_path / "shared" / "backup"
    result = backup_store(
        database, bundle, private_root=root, resource_observation=_safe_resource_observation()
    )
    assert result.status == "COMPLETE" and verify_backup(bundle).verified
    restored = root / "restored" / "store.sqlite3"
    assert (
        restore_backup(
            bundle, restored, private_root=root, resource_observation=_safe_resource_observation()
        ).status
        == "COMPLETE"
    )
    with open_store(restored, private_root=root) as store:
        repo = _repository(store)
        cutoffs = MatchEvidenceCutoffRepository(store)
        for frozen in (*old, successor):
            assert repo.get_by_id(frozen.freeze_id) == frozen
        for frozen, retained in zip(old, old_cutoffs, strict=True):
            assert cutoffs.replay_for_freeze(frozen.freeze_id, timing) == retained
        assert cutoffs.replay_for_freeze(successor.freeze_id, timing) == new_cutoffs
        assert repo.list_observations(successor.freeze_id) == (observation,)
        metadata = store.artifact_metadata(new_cutoffs[0].digest.removeprefix("sha256:"))
        assert metadata is not None
        (restored.parent / metadata.relative_path).write_bytes(b"corrupt")
        with pytest.raises(MatchEvidenceCutoffError):
            cutoffs.replay(new_cutoffs[0].cutoff_id)


def test_policy3_payload_refuses_changed_scopes_and_policy_bindings(tmp_path: Path) -> None:
    import json

    from matchvet.matchweek_membership import sha256_digest

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _six_scope_assessment(_persistable_empty_assessment(store, tmp_path))
        _persist(store, assessment)
        frozen = _repository(store).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
        )
        for mutation in (
            "order",
            "missing",
            "bel",
            "season",
            "scope_digest",
            "scope_version",
            "scope_order",
            "f01_contract",
            "f01_schema",
            "scope_label",
            "scope_season",
            "scope_bounds",
        ):
            raw = json.loads(canonical_json(frozen.to_payload()))
            if mutation == "order":
                raw["scopes"].reverse()
            elif mutation == "missing":
                raw["scopes"].pop()
            elif mutation == "bel":
                raw["scopes"].append(
                    {
                        **raw["scopes"][-1],
                        "scope_id": "belgian_pro_league:2026-27:2026-09-25",
                        "league_key": "belgian_pro_league",
                    }
                )
            elif mutation in ("scope_label", "scope_season", "scope_bounds"):
                key, value = {
                    "scope_label": ("league_key", "belgian_pro_league"),
                    "scope_season": ("season", "2025-26"),
                    "scope_bounds": ("window_start_utc", "2026-09-26T00:00:00+00:00"),
                }[mutation]
                raw["scopes"][0][key] = value
                payload = {key: value for key, value in raw.items() if key != "freeze_digest"}
                raw["freeze_digest"] = sha256_digest(canonical_json(payload))
            else:
                policy = json.loads(raw["policy"]["canonical_json"])
                if mutation == "season":
                    policy["active_scope"]["season"] = "2025-26"
                elif mutation == "scope_digest":
                    policy["active_scope"]["digest"] = "sha256:" + "0" * 64
                elif mutation == "scope_version":
                    policy["active_scope"]["version"] = 1
                elif mutation == "scope_order":
                    policy["active_scope"]["league_keys"].reverse()
                elif mutation == "f01_contract":
                    policy["fixture_coverage"]["contract_version"] = "fixture-coverage-v2-v2"
                else:
                    policy["fixture_coverage"]["schema_version"] = 3
                raw["policy"]["canonical_json"] = canonical_json(policy)
                raw["policy"]["digest"] = sha256_digest(raw["policy"]["canonical_json"])
            with pytest.raises(ValueError):
                freeze_from_canonical_json(canonical_json(raw))
        # Wrong season cannot silently select the current six scope.
        with pytest.raises(MatchweekMembershipError):
            _repository(store).freeze_exact(
                "2025-26", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
            )


def test_policy3_refuses_malformed_identity_payloads(tmp_path: Path) -> None:
    import json

    from matchvet.fixture_coverage_codec import decode_f01, encode_f01

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _six_scope_assessment(
            _persistable_schedule_assessment(
                store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
            )
        )
        for mutation in ("unsupported", "missing_revision", "unresolved_canonical"):
            raw = json.loads(encode_f01(assessment))
            identity = raw["identity_resolutions"][0]
            if mutation == "unsupported":
                identity["state"] = "TRANSITIONED"
            elif mutation == "missing_revision":
                identity["revision_ids"] = []
            else:
                identity["state"] = "UNRESOLVED_FIXTURE_IDENTITY"
                identity["reason_code"] = "IDENTITY_UNRESOLVED"
            with pytest.raises(ValueError):
                decode_f01(canonical_json(raw))


def test_observation_write_and_replay_refuse_changed_f01_scope_contract(tmp_path: Path) -> None:
    import json

    from matchvet.fixture_coverage_codec import encode_f01

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _six_scope_assessment(
            _persistable_schedule_assessment(
                store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
            )
        )
        _persist(store, assessment)
        repo = _repository(store)
        frozen = repo.freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
        )
        later = replace(
            assessment,
            identity_resolutions=(
                replace(assessment.identity_resolutions[0], candidate_id="new-candidate"),
            ),
            digest="",
        )
        FixtureCoverageRepository(store).persist(later)
        observation = repo.append_observation(frozen.freeze_id, later.digest)
        with store.transaction() as tx:
            tx.execute("DROP TRIGGER fixture_coverage_assessments_no_update")
        for mutation in (
            "digest",
            "version",
            "season",
            "order",
            "missing",
            "bel",
            "contract",
            "schema",
        ):
            raw = json.loads(encode_f01(later))
            if mutation == "digest":
                raw["active_scope"]["digest"] = "sha256:" + "0" * 64
            elif mutation == "version":
                raw["active_scope"]["version"] = 1
            elif mutation == "season":
                raw["active_scope"]["season"] = "2025-26"
            elif mutation == "order":
                raw["scope_assessments"].reverse()
            elif mutation == "missing":
                raw["scope_assessments"].pop()
            elif mutation == "bel":
                raw["scope_assessments"].append(raw["scope_assessments"][-1])
                raw["active_scope"]["league_keys"].append("belgian_pro_league")
            elif mutation == "contract":
                raw["contract_version"] = "fixture-coverage-v2-v2"
            else:
                raw["schema_version"] = 2
            with store.transaction() as tx:
                tx.execute(
                    "UPDATE fixture_coverage_assessments SET assessment_json=? "
                    "WHERE assessment_digest=?",
                    (canonical_json(raw), later.digest),
                )
            for action in (
                lambda: repo.append_observation(frozen.freeze_id, later.digest),
                lambda: repo.list_observations(frozen.freeze_id),
            ):
                with pytest.raises(MatchweekMembershipError):
                    action()
        with store.transaction() as tx:
            tx.execute(
                "UPDATE fixture_coverage_assessments SET assessment_json=? "
                "WHERE assessment_digest=?",
                (encode_f01(later), later.digest),
            )
        assert repo.get_by_id(frozen.freeze_id) == frozen
        assert repo.list_observations(frozen.freeze_id) == (observation,)


@pytest.mark.parametrize("corrupt", ("roles", "assertion", "history"))
def test_policy3_observation_inherits_lf14_integrity(tmp_path: Path, corrupt: str) -> None:
    from test_lf14 import _with_capture

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_schedule_assessment(
            store, tmp_path, (("2026-09-25", "12:00", "Start United", "Start City"),)
        )
        initial = _six_scope_assessment(legacy)
        _persist(store, initial)
        repo = _repository(store)
        frozen = repo.freeze_exact(
            "2026-27", "2026-09-25", initial.digest, "matchvet:matchweek-membership", "3"
        )
        later = _six_scope_assessment(_with_capture(store, tmp_path, legacy, time="13:00"))
        FixtureCoverageRepository(store).persist(later)
        new_capture = next(v.capture_id for v in later.provider_attempts if v.attempt_id == "extra")
        with store.transaction() as tx:
            if corrupt == "history":
                tx.execute("DROP TRIGGER conflict_assertions_no_delete")
                tx.execute(
                    "DELETE FROM conflict_assertions WHERE assertion_id IN "
                    "(SELECT assertion_id FROM source_assertions "
                    "WHERE capture_id=? AND predicate='kickoff')",
                    (new_capture,),
                )
            else:
                tx.execute("DROP TRIGGER source_assertions_no_update")
                if corrupt == "roles":
                    tx.execute(
                        "UPDATE source_assertions SET normalized_value_json='\"Start City\"' "
                        "WHERE capture_id=? AND predicate='home_team'",
                        (new_capture,),
                    )
                else:
                    tx.execute(
                        "UPDATE source_assertions SET normalized_value_json="
                        "'\"2026-09-26T13:00:00+01:00\"' "
                        "WHERE capture_id=? AND predicate='kickoff'",
                        (new_capture,),
                    )
        with pytest.raises(MatchweekMembershipError):
            repo.append_observation(frozen.freeze_id, later.digest)
        assert repo.get_by_id(frozen.freeze_id) == frozen
        assert repo.list_observations(frozen.freeze_id) == ()


def test_policy3_refuses_operator_attested_legacy_pair(tmp_path: Path) -> None:
    from test_matchweek_membership import _persist_attested_assessment

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        legacy = _persistable_empty_assessment(store, tmp_path)
        repository = FixtureCoverageRepository(store)
        repository.persist(legacy)
        attested = _persist_attested_assessment(store, repository, legacy)
        with pytest.raises(MatchweekMembershipError, match="contract pair"):
            _repository(store).freeze_exact(
                "2026-27", "2026-09-25", attested.digest, "matchvet:matchweek-membership", "3"
            )


def test_policy3_f07_preserves_exact_seconds_and_refuses_excluded_member(tmp_path: Path) -> None:
    from matchvet.match_evidence_cutoff import (
        CutoffPolicy,
        MatchEvidenceCutoffError,
        MatchEvidenceCutoffRepository,
    )

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _six_scope_assessment(
            _persistable_schedule_assessment(
                store,
                tmp_path,
                (
                    ("2026-09-25", "12:34:56", "Friday United", "Friday City"),
                    ("2026-09-28", "20:00", "Monday United", "Monday City"),
                    ("2026-09-24", "20:00", "Excluded United", "Excluded City"),
                ),
            )
        )
        _persist(store, assessment)
        frozen = _repository(store).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "3"
        )
        repo = MatchEvidenceCutoffRepository(store)
        policy = repo.persist_policy(
            CutoffPolicy(
                "exact-common-cutoff",
                "1",
                21600,
                rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
            )
        )
        cutoffs = repo.persist_for_freeze(frozen.freeze_id, policy)
        assert {c.cutoff_at_utc for c in cutoffs} == {"2026-09-25T05:34:56.000000+00:00"}
        assert len(cutoffs) == 2
        for cutoff in cutoffs:
            assert repo.replay(cutoff.cutoff_id).to_bytes() == cutoff.to_bytes()
        excluded = next(v for v in frozen.memberships if v.decision.value == "EXCLUDED")
        with pytest.raises(MatchEvidenceCutoffError):
            repo.persist_exact(frozen.freeze_id, excluded.membership_id, policy)

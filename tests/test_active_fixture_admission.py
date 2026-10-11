from pathlib import Path

from test_matchweek import _import_schedule, _schedule_csv

from matchvet.active_fixture_coverage import (
    active_fixture_scopes_for_matchweek,
    assess_active_fixture_coverage,
)
from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.fixture_coverage import (
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    ProviderAttempt,
    ProviderAttemptState,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_codec import encode_f01
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.ingestion import (
    FootballDataCSVParser,
    SourceCaptureInput,
    TeamIdentityPolicy,
    league_by_key,
)
from matchvet.matchweek import freeze_matchweek, load_active_fixture_admission, replay_matchweek


def test_mixed_store_filters_successor_and_preserves_legacy_freeze(tmp_path: Path) -> None:
    store, importer = _import_schedule(
        tmp_path,
        [("25/09/2026", "20:00", "Arsenal", "Chelsea")],
        "2026-09-20T12:00:00+00:00",
    )
    with store:
        for key, home, away in (
            ("serie_a", "Inter", "Milan"),
            ("la_liga", "Barcelona", "Real Madrid"),
            ("bundesliga", "Bayern Munich", "Dortmund"),
            ("ligue_1", "Paris SG", "Lyon"),
            ("liga_portugal", "Benfica", "Porto"),
        ):
            content = _schedule_csv([("25/09/2026", "20:00", home, away)])
            importer.import_dataset(
                FootballDataCSVParser().parse(content, league=league_by_key(key), season="2026-27"),
                content,
                SourceCaptureInput(
                    source_url=f"https://example.test/{key}.csv",
                    retrieved_at_utc="2026-09-20T12:00:00+00:00",
                    observed_terms="synthetic offline test",
                ),
            )
        content = _schedule_csv([("25/09/2026", "20:00", "Club Brugge", "Anderlecht")])
        belgium = importer.import_dataset(
            FootballDataCSVParser().parse(
                content, league=league_by_key("belgian_pro_league"), season="2026-27"
            ),
            content,
            SourceCaptureInput(
                source_url="https://example.test/B1.csv",
                retrieved_at_utc="2026-09-20T12:00:00+00:00",
                observed_terms="synthetic offline test",
            ),
        )
        belgian_ids = {
            item.fixture_id for item in importer.observations_for_capture(belgium.source_capture_id)
        }
        legacy = freeze_matchweek(store, "2026-09-25", as_of_utc="2026-09-24T12:00:00+00:00")
        admitted = load_active_fixture_admission(store, active_scope=SUCCESSOR_SIX_SCOPE)
        assert len(admitted.fixture_ids) == 6
        assert {item.league_key for item in admitted.revision_candidates} == set(
            SUCCESSOR_SIX_SCOPE.league_keys
        )
        assert len(legacy.memberships) == 7
        assert not belgian_ids.intersection(admitted.fixture_ids)
        assert belgian_ids.issubset({item.subject_id for item in legacy.memberships})
        # Retain seven real provenance graphs beside the six successor graph in F03.
        fixture_leagues = {item.fixture_id: item.league_key for item in importer.fixtures()}
        attempts = []
        revisions = []
        identities = []
        for capture in importer.source_captures():
            observations = importer.observations_for_capture(capture.capture_id)
            for observation in observations:
                assert observation.fixture_id is not None
                assert observation.revision_id is not None
                assert observation.revision_digest is not None
                key = fixture_leagues[observation.fixture_id]
                scope_id = f"{key}:2026-27:2026-09-25"
                attempts.append(
                    ProviderAttempt(
                        attempt_id=capture.capture_id,
                        scope_id=scope_id,
                        provider_id="synthetic",
                        capability_id="offline",
                        state=ProviderAttemptState.CAPTURED,
                        retrieved_at_utc="2026-09-20T12:00:00.000000+00:00",
                        capture_id=capture.capture_id,
                        capture_digest=capture.artifact_digest,
                    )
                )
                revisions.append(
                    FixtureRevisionReference(
                        scope_id=scope_id,
                        fixture_id=observation.fixture_id,
                        revision_id=observation.revision_id,
                        revision_digest=observation.revision_digest,
                        source_capture_ids=(capture.capture_id,),
                        source_assertion_ids=observation.source_assertion_ids,
                    )
                )
                identities.append(
                    FixtureIdentityResolution(
                        candidate_id=observation.fixture_id,
                        scope_id=scope_id,
                        state=FixtureIdentityState.RESOLVED,
                        canonical_fixture_id=observation.fixture_id,
                        revision_ids=(observation.revision_id,),
                    )
                )
        old_f01 = assess_fixture_coverage(
            scopes=fixture_scopes_for_matchweek("2026-09-25", season="2026-27"),
            provider_attempts=tuple(attempts),
            fixture_revisions=tuple(revisions),
            identity_resolutions=tuple(identities),
            coverage_evidence=(),
            freshness_results=(),
        )
        new_f01 = assess_active_fixture_coverage(
            active_scope=SUCCESSOR_SIX_SCOPE,
            scopes=active_fixture_scopes_for_matchweek(
                "2026-09-25", active_scope=SUCCESSOR_SIX_SCOPE
            ),
            provider_attempts=tuple(
                v for v in attempts if v.scope_id.split(":")[0] in SUCCESSOR_SIX_SCOPE.league_keys
            ),
            fixture_revisions=tuple(v for v in revisions if v.fixture_id in admitted.fixture_ids),
            identity_resolutions=tuple(
                v for v in identities if v.canonical_fixture_id in admitted.fixture_ids
            ),
            coverage_evidence=(),
            freshness_results=(),
        )
        repository = FixtureCoverageRepository(store)
        old_bytes = encode_f01(old_f01)
        repository.persist(old_f01)
        repository.persist(new_f01)
        old_replay = repository.get(old_f01.digest)
        new_replay = repository.get(new_f01.digest)
        assert old_replay is not None and new_replay is not None
        assert encode_f01(old_replay) == old_bytes
        assert len(old_replay.fixture_revisions) == 7
        assert len(new_replay.fixture_revisions) == 6
        assert not belgian_ids.intersection(
            {item.fixture_id for item in new_replay.fixture_revisions}
        )
        unresolved_content = _schedule_csv(
            [("25/09/2026", "20:00", "Unmapped Brussels", "Unmapped Antwerp")]
        )
        unresolved = importer.import_dataset(
            FootballDataCSVParser().parse(
                unresolved_content, league=league_by_key("belgian_pro_league"), season="2026-27"
            ),
            unresolved_content,
            SourceCaptureInput(
                source_url="https://example.test/bel-unresolved.csv",
                retrieved_at_utc="2026-09-20T12:00:00+00:00",
                observed_terms="synthetic offline test",
            ),
            identity_policy=TeamIdentityPolicy.KNOWN_ONLY,
        )
        assert unresolved.unresolved_rows == 1
        assert (
            load_active_fixture_admission(
                store, active_scope=SUCCESSOR_SIX_SCOPE
            ).unresolved_fixtures
            == ()
        )
        assert replay_matchweek(store, "2026-09-25").freeze == legacy
        assert load_active_fixture_admission(store, active_scope=SUCCESSOR_SIX_SCOPE) == admitted

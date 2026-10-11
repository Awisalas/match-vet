from pathlib import Path

import pytest

from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.ingestion import (
    DownloadedSource,
    FixtureHistoryAcquirer,
    FixtureHistoryImporter,
    IngestionPlan,
    StaticSourceFetcher,
    league_by_key,
    openfootball_text_url,
    openfootball_url,
)
from matchvet.store import open_store


def test_successor_requests_six_and_retains_all_failed_attempts(tmp_path: Path) -> None:
    plan = IngestionPlan.for_active_scope(
        active_scope=SUCCESSOR_SIX_SCOPE, matchweek_friday="2026-09-25"
    )
    fetcher = StaticSourceFetcher({})
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        acquired = FixtureHistoryAcquirer(
            FixtureHistoryImporter(store, private_root=tmp_path), fetcher
        ).acquire_scheduled_fixtures(plan)
        assert fetcher.calls == [
            url
            for key in SUCCESSOR_SIX_SCOPE.league_keys
            for url in (
                openfootball_url(league_by_key(key), "2026-27"),
                openfootball_text_url(league_by_key(key), "2026-27"),
            )
        ]
        assert len(acquired.assessment.provider_attempts) == 12
        assert {item.state.value for item in acquired.assessment.provider_attempts} == {
            "UNAVAILABLE"
        }
        assert len(acquired.assessment.scope_assessments) == 6
        assert not any("belg" in value.lower() for value in (*fetcher.calls, *acquired.diagnostics))
        assert (
            FixtureCoverageRepository(store).get(acquired.assessment.digest) == acquired.assessment
        )


def test_plan_is_explicit_and_legacy_digest_remains_historical() -> None:
    from dataclasses import replace

    import pytest

    legacy = IngestionPlan(current_season="2026-27", matchweek_friday="2026-09-25")
    successor = IngestionPlan.for_active_scope(
        active_scope=SUCCESSOR_SIX_SCOPE, matchweek_friday="2026-09-25"
    )
    assert legacy.plan_digest == "d6fe11946d2de1a2d48fbf55324f81677c7522574841da088b61a91851b39650"
    assert len(legacy.leagues) == 7
    assert successor.contract_id == "t06-acquisition-plan-v2"
    assert successor.plan_digest != legacy.plan_digest
    assert successor.run_key != legacy.run_key
    for changes in (
        {"leagues": legacy.leagues},
        {"leagues": successor.leagues[::-1]},
        {"leagues": successor.leagues[:-1]},
        {"current_season": "2025-26"},
    ):
        with pytest.raises(ValueError):
            replace(successor, **changes)


@pytest.mark.parametrize("authority", ("missing", "invalid", "withdrawn"))
def test_successor_refuses_live_fetch_before_contact(tmp_path: Path, authority: str) -> None:
    from test_source_transport import _Authorization, _Transport

    from matchvet.ingestion import ResumableSourceDownloader, SourceUnavailable

    plan = IngestionPlan.for_active_scope(
        active_scope=SUCCESSOR_SIX_SCOPE, matchweek_friday="2026-09-25"
    )
    transport = _Transport()
    auth = _Authorization("https://example.test/unrelated")
    auth.refused = authority == "withdrawn"
    downloader = ResumableSourceDownloader(
        tmp_path,
        http_transport=transport,
        authorization_repository=None if authority == "missing" else auth,
    )

    class AuthorizedFetcher:
        def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource:
            return downloader.fetch(
                url,
                cache_key=cache_key,
                refresh=refresh,
                authorization_decision_digest="synthetic-current",
            )

    with (
        open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store,
        pytest.raises(SourceUnavailable),
    ):
        FixtureHistoryAcquirer(
            FixtureHistoryImporter(store, private_root=tmp_path), AuthorizedFetcher()
        ).acquire_scheduled_fixtures(plan)
    assert transport.calls == []


def test_successor_retains_captured_and_unavailable_feeds(tmp_path: Path) -> None:
    from test_ingestion import _seed_existing_teams

    plan = IngestionPlan.for_active_scope(
        active_scope=SUCCESSOR_SIX_SCOPE, matchweek_friday="2026-09-25"
    )
    sources = {openfootball_url(league, "2026-27"): b'{"matches":[]}' for league in plan.leagues}
    sources[openfootball_url(plan.leagues[0], "2026-27")] = (
        b'{"matches":[{"date":"2026-09-25","time":"20:00",'
        b'"team1":"Arsenal","team2":"Coventry","score":{}}]}'
    )
    fetcher = StaticSourceFetcher(sources)
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        _seed_existing_teams(store, plan.leagues[0], ("Arsenal", "Coventry"))
        acquired = FixtureHistoryAcquirer(
            FixtureHistoryImporter(store, private_root=tmp_path), fetcher
        ).acquire_scheduled_fixtures(plan)
        assert len(acquired.assessment.provider_attempts) == 12
        assert {item.state.value for item in acquired.assessment.provider_attempts} == {
            "CAPTURED",
            "UNAVAILABLE",
        }
        assert len(acquired.assessment.fixture_revisions) == 1
        assert (
            FixtureCoverageRepository(store).get(acquired.assessment.digest) == acquired.assessment
        )

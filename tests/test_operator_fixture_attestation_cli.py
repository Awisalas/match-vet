from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from matchvet.cli import _parser
from matchvet.fixture_coverage import (
    FixtureCoverageAssessment,
    ProviderAttempt,
    ProviderAttemptState,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.operator_fixture_attestation_cli import handle_fixture_attestation
from matchvet.store import Store, open_store, termux_private_root


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


def _rewrite_legacy_assertion(
    store: Store,
    *,
    assertion_id: str,
    predicate: str,
    raw_value_json: str,
    normalized_value_json: str,
    event_time_utc: str,
    effective_time_utc: str | None,
) -> None:
    """Seed pre-LF04 source rows without weakening production immutability."""
    with store.transaction() as transaction:
        transaction.execute("DROP TRIGGER source_assertions_no_update")
        transaction.execute(
            """
            UPDATE source_assertions
            SET predicate = ?, raw_value_json = ?, normalized_value_json = ?,
                event_time_utc = ?, effective_time_utc = ?
            WHERE assertion_id = ?
            """,
            (
                predicate,
                raw_value_json,
                normalized_value_json,
                event_time_utc,
                effective_time_utc,
                assertion_id,
            ),
        )
        transaction.execute(
            """
            CREATE TRIGGER source_assertions_no_update
            BEFORE UPDATE ON source_assertions
            BEGIN SELECT RAISE(ABORT, 'source assertions are immutable'); END
            """
        )


def test_prepare_is_one_scope_compact_and_research_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "matchvet.sqlite3"
    base = _base_assessment()
    with open_store(store_path, private_root=termux_private_root()) as store:
        FixtureCoverageRepository(store).persist(base)

    import requests

    def refuse_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("LF02 must not request official websites.")

    monkeypatch.setattr(requests.sessions.Session, "request", refuse_network)
    arguments = _parser().parse_args(
        [
            "fixtures",
            "attest",
            "prepare",
            "--base",
            base.digest,
            "--league",
            "premier_league",
            "--season",
            "2026-27",
            "--friday",
            "2026-09-25",
            "--store",
            str(store_path),
        ]
    )

    assert handle_fixture_attestation(arguments) == 0
    output = capsys.readouterr().out
    assert "RESEARCH_ONLY" in output
    assert "premier_league:2026-27:2026-09-25" in output
    assert "(no MatchVet candidates)" in output
    assert "https://www.premierleague.com/" in output
    assert "serie_a:2026-27:2026-09-25" not in output
    assert output.count("\n") < 20
    assert '{"' not in output


def test_prepare_accepts_legacy_premier_league_date_only_kickoff(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet import operator_fixture_attestation_cli as attestation_cli
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        FootballDataCSVParser,
        IngestionPlan,
        SourceCaptureInput,
        StaticSourceFetcher,
        football_data_url,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )

    private_root = tmp_path / "private"
    private_root.mkdir()
    store_path = private_root / "matchvet.sqlite3"
    league = league_by_key("premier_league")
    text_source = openfootball_text_url(league, "2026-27")
    text_content = (
        b"= English Premier League 2026/27\n\nMatchday 1\n\nSat Oct 10 2026\n\nArsenal v Chelsea\n"
    )
    fetcher = StaticSourceFetcher(
        {
            openfootball_url(league, "2026-27"): b'{"matches":[]}',
            text_source: text_content,
        },
        retrieved_at_utc="2026-10-09T09:00:00+00:00",
    )

    with open_store(store_path, private_root=private_root) as store:
        assert store.status.schema_version == 14
        assert store.status.applied_migrations == tuple(range(1, 15))
        importer = FixtureHistoryImporter(store, private_root=private_root)
        history = (
            b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
            b"E0,21/08/2026,15:00,Arsenal,Chelsea,1,0,H\n"
        )
        importer.import_dataset(
            FootballDataCSVParser().parse(history, league=league, season="2026-27"),
            history,
            SourceCaptureInput(
                source_url=football_data_url(league, "2026-27"),
                retrieved_at_utc="2026-10-09T08:00:00+00:00",
                observed_terms=("Football-Data.co.uk restricted private local noncommercial use"),
            ),
        )
        scheduled = FixtureHistoryAcquirer(importer, fetcher).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-10-09",
            )
        )
        assert len(scheduled.assessment.fixture_revisions) == 1
        assert scheduled.assessment.fixture_revisions[0].source_assertion_ids
        assertion = next(
            item
            for item in importer.source_assertions()
            if item.predicate == "kickoff" and item.raw_value_json == '"2026-10-10"'
        )
        _rewrite_legacy_assertion(
            store,
            assertion_id=assertion.assertion_id,
            predicate=assertion.predicate,
            raw_value_json=assertion.raw_value_json or "",
            normalized_value_json=assertion.normalized_value_json or "",
            event_time_utc="2026-10-10",
            effective_time_utc="2026-10-10",
        )
        before = (
            store._connection_for_repository()
            .execute(
                """
            SELECT raw_value_json, normalized_value_json, event_time_utc, effective_time_utc
            FROM source_assertions WHERE assertion_id = ?
            """,
                (assertion.assertion_id,),
            )
            .fetchone()
        )
        assert tuple(before) == ('"2026-10-10"', '"2026-10-10"', "2026-10-10", "2026-10-10")
        FixtureCoverageRepository(store).persist(scheduled.assessment)

    monkeypatch.setattr(attestation_cli, "termux_private_root", lambda: private_root)
    arguments = _parser().parse_args(
        [
            "fixtures",
            "attest",
            "prepare",
            "--base",
            scheduled.assessment.digest,
            "--league",
            "premier_league",
            "--season",
            "2026-27",
            "--friday",
            "2026-10-09",
            "--store",
            str(store_path),
            "--json",
        ]
    )

    assert handle_fixture_attestation(arguments) == 0, capsys.readouterr().out
    output = capsys.readouterr().out
    manifest_result = json.loads(output)
    assert manifest_result["candidate_count"] == 1
    assert (
        manifest_result["candidate_manifest_contract"] == "operator-fixture-candidate-manifest-v2"
    )
    assert manifest_result["candidate_manifest_schema"] == 2
    assert manifest_result["candidate_manifest_digest"].startswith("sha256:")
    prepared_revision = manifest_result["entries"][0]["revisions"][0]
    assert prepared_revision["kickoff_precision"] == "DATE"
    assert prepared_revision["kickoff_utc"] is None
    assert prepared_revision["kickoff_local_text"] == "2026-10-10"
    assert manifest_result["entries"][0]["schedule_relation"] == "PROVISIONAL"

    with open_store(store_path, private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        manifest = repository.build_candidate_manifest(
            scheduled.assessment, "premier_league:2026-27:2026-10-09"
        )
        replay = repository.build_candidate_manifest(
            scheduled.assessment, "premier_league:2026-27:2026-10-09"
        )
        revision = manifest.entries[0].revision_facts[0]
        from matchvet.operator_fixture_attestation import (
            OperatorAttestationOutcome,
            OperatorComparisonConfirmations,
            make_operator_coverage_attestation,
            policy_publications_for_scope,
        )

        attestation = make_operator_coverage_attestation(
            base_assessment=scheduled.assessment,
            candidate_manifest=manifest,
            operator_id="lf04-test-replay",
            verified_at_utc="2026-10-09T10:00:00.000000+00:00",
            publications=policy_publications_for_scope(manifest.scope),
            expected_official_fixture_count=1,
            candidate_confirmations=(),
            confirmations=OperatorComparisonConfirmations(
                all_official_fixtures_represented=False,
                no_extra_matchvet_fixture=False,
                complete_official_publication_covers_scope=False,
                pairing_calendar_layer_checked=False,
                exact_schedule_layer_checked=False,
                latest_applicable_update_checked=False,
                complete_publication_affirms_empty_scope=False,
            ),
            outcome=OperatorAttestationOutcome.UNCERTAIN,
            reason="Isolated LF04 replay coverage.",
        )
        persisted_attestation = repository.persist_attestation(attestation)
        replayed_attestation = repository.get_attestation_artifact(
            persisted_attestation.artifact_digest
        )
        after = (
            store._connection_for_repository()
            .execute(
                """
            SELECT raw_value_json, normalized_value_json, event_time_utc, effective_time_utc
            FROM source_assertions WHERE assertion_id = ?
            """,
                (assertion.assertion_id,),
            )
            .fetchone()
        )
    kickoff = next(
        item for item in manifest.entries[0].assertion_facts if item.predicate == "kickoff"
    )
    home_assertion = next(
        item for item in manifest.entries[0].assertion_facts if item.predicate == "home_team"
    )
    home_assertion_id = home_assertion.assertion_id

    assert kickoff.raw_value_json == '"2026-10-10"'
    assert kickoff.normalized_value_json == '"2026-10-10"'
    assert kickoff.event_time_utc is None
    assert kickoff.effective_time_utc is None
    assert revision.kickoff_precision == "DATE"
    assert revision.kickoff_utc is None
    assert revision.kickoff_local_text == "2026-10-10"
    assert persisted_attestation.attestation.candidate_manifest == manifest
    assert replayed_attestation == attestation
    assert manifest.digest == replay.digest == manifest_result["candidate_manifest_digest"]
    assert tuple(after) == tuple(before)

    def assert_invalid_legacy_values(
        *,
        predicate: str,
        raw_value_json: str,
        normalized_value_json: str,
        event_time_utc: str,
        effective_time_utc: str | None,
        target_assertion_id: str | None = None,
    ) -> None:
        with open_store(store_path, private_root=private_root) as store:
            _rewrite_legacy_assertion(
                store,
                assertion_id=target_assertion_id or assertion.assertion_id,
                predicate=predicate,
                raw_value_json=raw_value_json,
                normalized_value_json=normalized_value_json,
                event_time_utc=event_time_utc,
                effective_time_utc=effective_time_utc,
            )
            with pytest.raises(ValueError):
                FixtureCoverageRepository(store).build_candidate_manifest(
                    scheduled.assessment, "premier_league:2026-27:2026-10-09"
                )

    assert_invalid_legacy_values(
        predicate="kickoff",
        raw_value_json='"2026-10-10"',
        normalized_value_json='"2026-10-10"',
        event_time_utc="2026-10-10T00:00:00",
        effective_time_utc="2026-10-10T00:00:00",
    )
    assert_invalid_legacy_values(
        predicate="kickoff",
        raw_value_json='"2026-10-10"',
        normalized_value_json='"2026-10-10"',
        event_time_utc="2026-02-31",
        effective_time_utc="2026-02-31",
    )
    assert_invalid_legacy_values(
        predicate="kickoff",
        raw_value_json='"2026-10-10"',
        normalized_value_json='"2026-10-11"',
        event_time_utc="2026-10-10",
        effective_time_utc="2026-10-10",
    )
    assert_invalid_legacy_values(
        predicate="kickoff",
        raw_value_json='"2026-10-11"',
        normalized_value_json='"2026-10-10"',
        event_time_utc="2026-10-10",
        effective_time_utc="2026-10-10",
    )
    assert_invalid_legacy_values(
        predicate="kickoff",
        raw_value_json='"2026-10-10"',
        normalized_value_json='"2026-10-10"',
        event_time_utc="2026-10-10",
        effective_time_utc="2026-10-10T00:00:00+00:00",
    )
    assert_invalid_legacy_values(
        predicate="home_team",
        raw_value_json=home_assertion.raw_value_json or "",
        normalized_value_json=home_assertion.normalized_value_json or "",
        event_time_utc="2026-10-10",
        effective_time_utc="2026-10-10",
        target_assertion_id=home_assertion_id,
    )


def test_record_has_no_default_yes_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "matchvet.sqlite3"
    base = _base_assessment()
    with open_store(store_path, private_root=termux_private_root()) as store:
        FixtureCoverageRepository(store).persist(base)

    answers = iter(
        (
            "y",
            "1",
            "1",
            "1",
            "https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season",
            "all 380 fixtures",
            "",
            "y",
            "y",
            "https://www.premierleague.com/en/news/1235133",
            "updating calendar",
            "",
            "y",
            "n",
            "c",
            "maybe",
        )
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    arguments = _parser().parse_args(
        [
            "fixtures",
            "attest",
            "record",
            "--base",
            base.digest,
            "--league",
            "premier_league",
            "--season",
            "2026-27",
            "--friday",
            "2026-09-25",
            "--operator-id",
            "offline-operator",
            "--store",
            str(store_path),
        ]
    )

    assert handle_fixture_attestation(arguments) == 1
    output = capsys.readouterr().out
    assert "confirmations have no default" in output
    with open_store(store_path, private_root=termux_private_root()) as store:
        assert (
            store._connection_for_repository()
            .execute("SELECT count(*) FROM artifacts")
            .fetchone()[0]
            == 0
        )


def test_record_can_persist_a_clear_refusal_without_an_official_reference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "matchvet.sqlite3"
    base = _base_assessment()
    with open_store(store_path, private_root=termux_private_root()) as store:
        FixtureCoverageRepository(store).persist(base)

    answers = iter(("n", "r", "No policy-approved complete publication was available."))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    arguments = _parser().parse_args(
        [
            "fixtures",
            "attest",
            "record",
            "--base",
            base.digest,
            "--league",
            "premier_league",
            "--season",
            "2026-27",
            "--friday",
            "2026-09-25",
            "--operator-id",
            "offline-operator",
            "--store",
            str(store_path),
        ]
    )

    assert handle_fixture_attestation(arguments) == 0
    assert "Status: REFUSED" in capsys.readouterr().out
    with open_store(store_path, private_root=termux_private_root()) as store:
        row = (
            store._connection_for_repository()
            .execute("SELECT media_type FROM artifacts")
            .fetchone()
        )
        assert row == ("application/vnd.matchvet.operator-fixture-attestation-v2+json",)


def test_assemble_uses_seven_explicit_artifacts_and_prints_compact_freeze_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet import operator_fixture_attestation_cli as attestation_cli
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.operator_fixture_attestation import (
        AttestationArtifactReference,
        OperatorAttestationOutcome,
        OperatorComparisonConfirmations,
        make_operator_coverage_attestation,
        policy_publications_for_scope,
    )

    store_path = tmp_path / "matchvet.sqlite3"
    base = _base_assessment()
    fixed_now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    monkeypatch.setattr(
        attestation_cli,
        "MatchweekMembershipRepository",
        lambda store: MatchweekMembershipRepository(store, clock=lambda: fixed_now),
    )
    with open_store(store_path, private_root=termux_private_root()) as store:
        repository = FixtureCoverageRepository(store)
        repository.persist(base)
        references: list[AttestationArtifactReference] = []
        for item in base.scope_assessments:
            manifest = repository.build_candidate_manifest(base, item.scope.scope_id)
            test_urls = {
                "ligue-1-programmation": (
                    "https://ligue1.com/fr/articles/l1_article_90001-programmation-de-la-journee"
                ),
                "liga-portugal-round-updates": (
                    "https://www.ligaportugal.pt/news/90001/horarios-da-jornada-da-liga"
                ),
            }
            publications = tuple(
                replace(publication, official_url=test_urls[publication.publication_id])
                if publication.publication_id in test_urls
                else publication
                for publication in policy_publications_for_scope(item.scope)
            )
            attestation = make_operator_coverage_attestation(
                base_assessment=base,
                candidate_manifest=manifest,
                operator_id="offline-operator",
                verified_at_utc="2026-09-17T12:00:00.000000+00:00",
                publications=publications,
                expected_official_fixture_count=0,
                candidate_confirmations=(),
                confirmations=OperatorComparisonConfirmations(
                    all_official_fixtures_represented=True,
                    no_extra_matchvet_fixture=True,
                    complete_official_publication_covers_scope=True,
                    pairing_calendar_layer_checked=True,
                    exact_schedule_layer_checked=True,
                    latest_applicable_update_checked=True,
                    complete_publication_affirms_empty_scope=True,
                ),
                outcome=OperatorAttestationOutcome.CERTIFIED,
                reason=None,
            )
            references.append(repository.persist_attestation(attestation))

    arguments = _parser().parse_args(
        [
            "fixtures",
            "attest",
            "assemble",
            "--base",
            base.digest,
            "--season",
            "2026-27",
            "--friday",
            "2026-09-25",
            "--store",
            str(store_path),
            *[
                value
                for reference in references
                for value in ("--attestation-artifact", reference.artifact_digest)
            ],
        ]
    )

    assert handle_fixture_attestation(arguments) == 0
    output = capsys.readouterr().out
    assert "Status: F06_FROZEN" in output
    assert "F01 v2 base:" in output
    assert "F01 v3:" in output
    assert "F06 freeze:" in output
    assert output.count("CONFIRMED_EMPTY") == 7
    assert len(output.splitlines()) <= 15
    assessment_digest = next(
        line.removeprefix("F01 v3: ") for line in output.splitlines() if line.startswith("F01 v3:")
    )
    with open_store(store_path, private_root=termux_private_root()) as store:
        assert FixtureCoverageRepository(store).get(assessment_digest) is not None

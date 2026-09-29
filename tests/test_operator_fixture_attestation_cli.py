from __future__ import annotations

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
from matchvet.store import open_store, termux_private_root


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
        assert row == ("application/vnd.matchvet.operator-fixture-attestation-v1+json",)


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

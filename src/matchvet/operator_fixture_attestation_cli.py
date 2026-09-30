"""Compact interactive Termux workflow for LF02 operator fixture attestations."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from matchvet.fixture_coverage import (
    FixtureCoverageAssessment,
    FixtureScope,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import (
    FixtureCoverageIntegrityError,
    FixtureCoverageRepository,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.operator_fixture_attestation import (
    AttestationArtifactReference,
    CandidateAssertionFact,
    CandidateComparisonConfirmation,
    CandidateManifestEntryV2,
    CandidateManifestEntryValue,
    CandidateManifestValue,
    OfficialPublicationReference,
    OperatorAttestationOutcome,
    OperatorComparisonConfirmations,
    OperatorCoverageAttestation,
    OperatorPublicationRule,
    derive_attested_fixture_coverage,
    make_operator_coverage_attestation,
    operator_attestation_policy_v1,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import (
    Store,
    StoreMode,
    default_database_path,
    open_store,
    termux_private_root,
)

if TYPE_CHECKING:
    from argparse import _SubParsersAction

_PAGE_SIZE = 20


def add_fixture_attestation_parser(
    commands: _SubParsersAction[argparse.ArgumentParser],
) -> None:
    fixtures = commands.add_parser("fixtures", help="inspect scheduled-fixture research evidence")
    fixture_commands = fixtures.add_subparsers(dest="fixtures_command", required=True)
    from matchvet.operator_fixture_observation_cli import add_fixture_observation_parser

    add_fixture_observation_parser(fixture_commands)
    attest = fixture_commands.add_parser(
        "attest", help="record Research-Only official fixture comparisons"
    )
    attest_commands = attest.add_subparsers(dest="attest_command", required=True)
    prepare = attest_commands.add_parser("prepare", help="show one exact F01 scope checklist")
    _add_scope_options(prepare)
    prepare.add_argument("--page", type=int, default=1, help="candidate page, starting at 1")
    record = attest_commands.add_parser("record", help="record one immutable scope attestation")
    _add_scope_options(record)
    record.add_argument("--operator-id", required=True, help="stable local operator identifier")
    assemble = attest_commands.add_parser(
        "assemble", help="derive v3 from an explicit set of seven attestation artifacts"
    )
    assemble.add_argument("--base", required=True, help="exact persisted F01 v2 assessment digest")
    assemble.add_argument(
        "--attestation-artifact",
        action="append",
        required=True,
        dest="attestation_artifacts",
        metavar="SHA256",
        help="explicit persisted attestation artifact digest; repeat exactly seven times",
    )
    assemble.add_argument("--season", required=True, help="explicit season in YYYY-YY form")
    assemble.add_argument("--friday", required=True, help="explicit Matchweek Friday YYYY-MM-DD")
    _add_store_options(prepare)
    _add_store_options(record)
    _add_store_options(assemble)


def _add_scope_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", required=True, help="exact persisted F01 v2 assessment digest")
    parser.add_argument("--league", required=True, help="one configured league key")
    parser.add_argument("--season", required=True, help="season in YYYY-YY form")
    parser.add_argument("--friday", required=True, help="Matchweek Friday YYYY-MM-DD")


def _add_store_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store", type=Path, help="authoritative store; defaults to MatchVet store"
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON result")


def handle_fixture_attestation(arguments: argparse.Namespace) -> int:
    try:
        if arguments.attest_command == "prepare":
            return _prepare(arguments)
        if arguments.attest_command == "record":
            return _record(arguments)
        if arguments.attest_command == "assemble":
            return _assemble(arguments)
        raise ValueError("Choose prepare, record, or assemble.")
    except EOFError, KeyboardInterrupt:
        return _result(
            arguments,
            {"status": "REFUSED", "reason": "Operator input ended before every required answer."},
            exit_code=1,
        )
    except (
        FixtureCoverageIntegrityError,
        OSError,
        RuntimeError,
        sqlite3.DatabaseError,
        TypeError,
        ValueError,
    ) as error:
        return _result(arguments, {"status": "REFUSED", "reason": str(error)}, exit_code=1)


def _prepare(arguments: argparse.Namespace) -> int:
    with _open(arguments) as store:
        repository = FixtureCoverageRepository(store)
        base, scope = _selected_scope(repository, arguments)
        manifest = repository.build_candidate_manifest(base, scope.scope_id)
        rules = _rules_for_scope(scope)
        selected_entries = _page_entries(manifest.entries, arguments.page)
        page_count = max(1, (len(manifest.entries) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if arguments.as_json:
            return _result(
                arguments,
                {
                    "mode": "RESEARCH_ONLY",
                    "base_assessment_digest": base.digest,
                    "candidate_count": manifest.candidate_count,
                    "candidate_manifest_contract": manifest.contract_version,
                    "candidate_manifest_digest": manifest.digest,
                    "candidate_manifest_schema": manifest.schema_version,
                    "entries": [_entry_json(item) for item in selected_entries],
                    "entry_count": len(manifest.entries),
                    "friday": scope.matchweek_friday,
                    "league": scope.league_key,
                    "official_publications": [_rule_json(item) for item in rules],
                    "scope_id": scope.scope_id,
                    "season": scope.season,
                    "page": arguments.page,
                    "page_count": page_count,
                },
            )
        print("MatchVet fixture attestation | RESEARCH_ONLY")
        print(f"Base: {base.digest}")
        print(f"Scope: {scope.scope_id}")
        print(f"Bounds: [{scope.window_start_utc}, {scope.window_end_utc})")
        print(
            f"Candidates: {manifest.candidate_count}; manifest {manifest.digest}; "
            f"page {arguments.page}/{page_count}"
        )
        _print_candidate_page(selected_entries, (arguments.page - 1) * _PAGE_SIZE)
        print("Open official sources manually; MatchVet makes no official-site requests.")
        for index, rule in enumerate(rules, start=1):
            layers = ",".join(rule.supported_layers)
            print(f"[{index}] {rule.publication_id} ({layers}) {rule.example_url}")
        print("Use record with the same base, league, season, and Friday.")
        return 0


def _record(arguments: argparse.Namespace) -> int:
    verified_at = datetime.now(UTC).isoformat(timespec="microseconds")
    with _open(arguments) as store:
        repository = FixtureCoverageRepository(store)
        base, scope = _selected_scope(repository, arguments)
        manifest = repository.build_candidate_manifest(base, scope.scope_id)
        rules = _rules_for_scope(scope)
        _print_record_checklist(base, scope, manifest, rules)

        if not _ask_yes_no("Is a policy-approved official publication available to cite"):
            outcome = _read_refusal_or_uncertainty()
            no_source_reason = _read_required("Refusal or uncertainty reason")
            unchecked = OperatorComparisonConfirmations(
                all_official_fixtures_represented=False,
                no_extra_matchvet_fixture=False,
                complete_official_publication_covers_scope=False,
                pairing_calendar_layer_checked=False,
                exact_schedule_layer_checked=False,
                latest_applicable_update_checked=False,
                complete_publication_affirms_empty_scope=False,
            )
            attestation = make_operator_coverage_attestation(
                base_assessment=base,
                candidate_manifest=manifest,
                operator_id=arguments.operator_id,
                verified_at_utc=verified_at,
                publications=(),
                expected_official_fixture_count=None,
                candidate_confirmations=(),
                confirmations=unchecked,
                outcome=outcome,
                reason=no_source_reason,
            )
            return _persist_attestation_result(arguments, repository, scope, attestation)

        selected_rules = _select_rules(rules)
        publications = _collect_publication_references(scope, selected_rules)
        outcome = _read_outcome()
        candidate_confirmations = _candidate_comparison_pages(manifest.entries)
        confirmations = OperatorComparisonConfirmations(
            all_official_fixtures_represented=_ask_yes_no(
                "Every official fixture in this scope is represented in MatchVet"
            ),
            no_extra_matchvet_fixture=_ask_yes_no(
                "No MatchVet candidate is extra to the official scope"
            ),
            complete_official_publication_covers_scope=_ask_yes_no(
                "A complete official publication covers this exact scope"
            ),
            pairing_calendar_layer_checked=_ask_yes_no(
                "The official pairing/calendar layer was checked"
            ),
            exact_schedule_layer_checked=_ask_yes_no("Exact dates and kickoffs were checked"),
            latest_applicable_update_checked=_ask_yes_no(
                "The latest applicable official scheduling update was checked"
            ),
            complete_publication_affirms_empty_scope=(
                _ask_yes_no("A complete publication affirmatively shows this scope is empty")
                if manifest.candidate_count == 0
                else False
            ),
        )
        expected_count = _read_nonnegative_int("Expected official fixture count")
        attestation_reason = (
            _read_required("Refusal or uncertainty reason")
            if outcome is not OperatorAttestationOutcome.CERTIFIED
            else None
        )
        attestation = make_operator_coverage_attestation(
            base_assessment=base,
            candidate_manifest=manifest,
            operator_id=arguments.operator_id,
            verified_at_utc=verified_at,
            publications=publications,
            expected_official_fixture_count=expected_count,
            candidate_confirmations=candidate_confirmations,
            confirmations=confirmations,
            outcome=outcome,
            reason=attestation_reason,
        )
        return _persist_attestation_result(arguments, repository, scope, attestation)


def _persist_attestation_result(
    arguments: argparse.Namespace,
    repository: FixtureCoverageRepository,
    scope: FixtureScope,
    attestation: OperatorCoverageAttestation,
) -> int:
    artifact = repository.persist_attestation(attestation)
    return _result(
        arguments,
        {
            "mode": "RESEARCH_ONLY",
            "status": attestation.outcome.value,
            "reason": attestation.reason or None,
            "scope_id": scope.scope_id,
            "attestation_id": attestation.attestation_id,
            "attestation_digest": attestation.digest,
            "artifact_digest": artifact.artifact_digest,
            "verified_at_utc": attestation.verified_at_utc,
        },
    )


def _assemble(arguments: argparse.Namespace) -> int:
    if len(arguments.attestation_artifacts) != 7:
        raise ValueError("Assembly requires exactly seven explicit --attestation-artifact values.")
    scopes = fixture_scopes_for_matchweek(arguments.friday, season=arguments.season)
    with _open(arguments) as store:
        repository = FixtureCoverageRepository(store)
        base = repository.get(arguments.base)
        if (
            base is None
            or base.contract_version != "fixture-coverage-v2-v2"
            or base.schema_version != 2
        ):
            raise ValueError(
                "Assembly base must name an existing persisted automatic F01 v2 value."
            )
        base = cast(FixtureCoverageAssessment, base)
        if tuple(item.scope for item in base.scope_assessments) != scopes:
            raise ValueError("Explicit season and Friday do not match the persisted base.")
        references = tuple(
            AttestationArtifactReference(
                attestation=repository.get_attestation_artifact(digest),
                artifact_digest=digest,
            )
            for digest in arguments.attestation_artifacts
        )
        assessment = derive_attested_fixture_coverage(base, references)
        repository.persist(assessment)
        records = build_provider_health_records(assessment)
        ProviderHealthRepository(store).persist_many(records)
        result: dict[str, object] = {
            "mode": "RESEARCH_ONLY",
            "status": "F01_V3_PERSISTED",
            "base_assessment_digest": base.digest,
            "assessment_digest": assessment.digest,
            "scope_outcomes": [
                {
                    "league": item.scope.league_key,
                    "coverage": item.coverage_state.value,
                }
                for item in assessment.scope_assessments
            ],
            "provider_health_records": len(records),
        }
        try:
            frozen = MatchweekMembershipRepository(store).freeze_exact(
                season=arguments.season,
                matchweek_friday=arguments.friday,
                assessment_digest=assessment.digest,
                policy_id="matchvet:matchweek-membership",
                policy_version="1",
            )
        except (RuntimeError, ValueError, sqlite3.DatabaseError) as error:
            result.update(
                {"status": "F06_REFUSED", "freeze_digest": None, "freeze_reason": str(error)}
            )
            return _result(arguments, result, exit_code=1)
        result.update(
            {
                "status": "F06_FROZEN",
                "freeze_digest": frozen.freeze_digest,
                "freeze_id": frozen.freeze_id,
            }
        )
        return _result(arguments, result)


def _open(arguments: argparse.Namespace) -> Store:
    database_path = arguments.store or default_database_path()
    store = open_store(database_path, private_root=termux_private_root())
    if store.status.mode is not StoreMode.READ_WRITE:
        issue = store.status.issues[0]
        store.close()
        raise RuntimeError(f"{issue.code}: {issue.message}")
    return store


def _selected_scope(
    repository: FixtureCoverageRepository, arguments: argparse.Namespace
) -> tuple[FixtureCoverageAssessment, FixtureScope]:
    base = repository.get(arguments.base)
    if (
        base is None
        or base.contract_version != "fixture-coverage-v2-v2"
        or base.schema_version != 2
    ):
        raise ValueError(
            "The explicit base digest must name a persisted automatic F01 v2 assessment."
        )
    base = cast(FixtureCoverageAssessment, base)
    scope = next(
        (
            item.scope
            for item in base.scope_assessments
            if item.scope.league_key == arguments.league
        ),
        None,
    )
    if scope is None or (scope.season, scope.matchweek_friday) != (
        arguments.season,
        arguments.friday,
    ):
        raise ValueError("The explicit league, season, or Friday differs from the persisted base.")
    return base, scope


def _rules_for_scope(scope: FixtureScope) -> tuple[OperatorPublicationRule, ...]:
    return tuple(
        item
        for item in operator_attestation_policy_v1().publication_rules
        if item.league_key == scope.league_key
    )


def _page_entries(
    entries: tuple[CandidateManifestEntryValue, ...], page: int
) -> tuple[CandidateManifestEntryValue, ...]:
    if page < 1:
        raise ValueError("Candidate page must be at least 1.")
    page_count = max(1, (len(entries) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    if page > page_count:
        raise ValueError(f"Candidate page must be between 1 and {page_count}.")
    return entries[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]


def _print_candidate_page(
    entries: tuple[CandidateManifestEntryValue, ...], start_index: int
) -> None:
    selected = entries
    if not selected:
        print("  (no MatchVet candidates)")
        return
    for index, entry in enumerate(selected, start=start_index + 1):
        identity = entry.canonical_fixture_id or entry.reason_code or "UNRESOLVED"
        flags = (
            ",".join(
                flag
                for flag, active in (
                    ("CONFLICT", entry.has_schedule_conflict),
                    ("PROVISIONAL", entry.has_provisional_scheduling),
                    ("UNRESOLVED", entry.canonical_fixture_id is None),
                )
                if active
            )
            or "OK"
        )
        relation = (
            entry.schedule_relation.value if isinstance(entry, CandidateManifestEntryV2) else flags
        )
        print(f"  {index}. {entry.candidate_id} {identity} [{relation}; {flags}]")
        for revision in entry.revision_facts:
            kickoff = revision.kickoff_utc or revision.kickoff_local_text or revision.kickoff_state
            home = _team_label(entry.assertion_facts, "home_team") or revision.home_team_id
            away = _team_label(entry.assertion_facts, "away_team") or revision.away_team_id
            revision_identity = (
                f"rev {revision.reference.revision_id[:12]}/"
                f"{revision.reference.revision_digest[:12]}"
            )
            print(
                f"     {home} - {away}; {kickoff}; {revision.fixture_status}; {revision_identity}"
            )


def _team_label(assertions: Sequence[CandidateAssertionFact], predicate: str) -> str | None:
    values = sorted(
        {
            value
            for item in assertions
            if item.predicate == predicate
            if (value := _short_assertion_value(item.raw_value_json)) is not None
        }
    )
    return "|".join(values) if values else None


def _short_assertion_value(encoded: str | None) -> str | None:
    if encoded is None:
        return None
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError:
        value = encoded
    if isinstance(value, str):
        return value[:80]
    return str(value)[:80]


def _print_record_checklist(
    base: FixtureCoverageAssessment,
    scope: FixtureScope,
    manifest: CandidateManifestValue,
    rules: tuple[OperatorPublicationRule, ...],
) -> None:
    print("MatchVet fixture attestation | RESEARCH_ONLY")
    print(f"Base: {base.digest}")
    print(f"Scope: {scope.scope_id} [{scope.window_start_utc}, {scope.window_end_utc})")
    print(f"Candidates: {manifest.candidate_count}; manifest {manifest.digest}")
    for index, rule in enumerate(rules, start=1):
        print(f"[{index}] {rule.publication_id} {rule.example_url}")


def _candidate_comparison_pages(
    entries: tuple[CandidateManifestEntryValue, ...],
) -> tuple[CandidateComparisonConfirmation, ...]:
    page_count = max(1, (len(entries) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    confirmations: list[CandidateComparisonConfirmation] = []
    for page in range(1, page_count + 1):
        selected = _page_entries(entries, page)
        print(f"Candidates page {page}/{page_count}")
        _print_candidate_page(selected, (page - 1) * _PAGE_SIZE)
        confirmations.extend(_candidate_answers(entry.candidate_id) for entry in selected)
    return tuple(confirmations)


def _select_rules(
    rules: tuple[OperatorPublicationRule, ...],
) -> tuple[OperatorPublicationRule, ...]:
    selected: dict[str, OperatorPublicationRule] = {}
    for layer in ("pairings", "exact_schedule", "latest_update"):
        available = tuple(item for item in rules if layer in item.supported_layers)
        options = ", ".join(
            f"{index}:{item.publication_id}" for index, item in enumerate(available, start=1)
        )
        number = _read_required(f"Publication number for {layer} [{options}]")
        if not number.isdecimal() or not 1 <= int(number) <= len(available):
            raise ValueError(f"Invalid policy publication selection for {layer}.")
        rule = available[int(number) - 1]
        selected[rule.publication_id] = rule
    return tuple(selected[key] for key in sorted(selected))


def _collect_publication_references(
    scope: FixtureScope,
    rules: tuple[OperatorPublicationRule, ...],
) -> tuple[OfficialPublicationReference, ...]:
    references = []
    for rule in rules:
        print(f"Checked {rule.publication_id}: {rule.example_url}")
        url = _read_required("Exact official URL checked")
        title = _read_required("Official title or publication identifier")
        publication_date = input("Publication date (blank if unavailable): ").strip() or None
        covers_scope = _ask_yes_no("Does this publication explicitly cover the requested scope")
        complete = _ask_yes_no("Is this a complete official publication for the requested scope")
        references.append(
            OfficialPublicationReference(
                publication_id=rule.publication_id,
                publisher_id=rule.publisher_id,
                competition_id=rule.competition_id,
                official_url=url,
                title_or_publication_id=title,
                publication_date=publication_date,
                publication_type=rule.publication_type,
                claim_scope_id=scope.scope_id,
                covers_exact_scope=covers_scope,
                complete_for_scope=complete,
            )
        )
    return tuple(references)


def _candidate_answers(candidate_id: str) -> CandidateComparisonConfirmation:
    print(f"Compare {candidate_id} against the checked official publication:")
    return CandidateComparisonConfirmation(
        candidate_id=candidate_id,
        identity_matches=_ask_yes_no("  Fixture identity matches"),
        date_matches=_ask_yes_no("  Applicable date matches"),
        kickoff_matches=_ask_yes_no("  Exact kickoff matches"),
        status_matches=_ask_yes_no("  Fixture status matches"),
    )


def _read_outcome() -> OperatorAttestationOutcome:
    answer = _read_required("Outcome [c=certified, r=refused, u=uncertain]").lower()
    outcomes = {
        "c": OperatorAttestationOutcome.CERTIFIED,
        "r": OperatorAttestationOutcome.REFUSED,
        "u": OperatorAttestationOutcome.UNCERTAIN,
    }
    if answer not in outcomes:
        raise ValueError("Outcome must be entered explicitly as c, r, or u.")
    return outcomes[answer]


def _read_refusal_or_uncertainty() -> OperatorAttestationOutcome:
    answer = _read_required("Outcome [r=refused, u=uncertain]").lower()
    outcomes = {
        "r": OperatorAttestationOutcome.REFUSED,
        "u": OperatorAttestationOutcome.UNCERTAIN,
    }
    if answer not in outcomes:
        raise ValueError("Without a policy-approved source, outcome must be r or u.")
    return outcomes[answer]


def _ask_yes_no(question: str) -> bool:
    answer = _read_required(f"{question} [y/n]").lower()
    if answer not in {"y", "n"}:
        raise ValueError("Enter y or n explicitly; confirmations have no default.")
    return answer == "y"


def _read_required(prompt: str) -> str:
    value = input(f"{prompt}: ").strip()
    if not value:
        raise ValueError(f"{prompt} is required.")
    return value


def _read_nonnegative_int(prompt: str) -> int:
    value = _read_required(prompt)
    if not value.isdecimal():
        raise ValueError(f"{prompt} must be a nonnegative integer.")
    return int(value)


def _entry_json(entry: CandidateManifestEntryValue) -> dict[str, object]:
    result: dict[str, object] = {
        "candidate_id": entry.candidate_id,
        "canonical_fixture_id": entry.canonical_fixture_id,
        "identity_state": entry.identity_state.value,
        "reason_code": entry.reason_code,
        "has_schedule_conflict": entry.has_schedule_conflict,
        "has_provisional_scheduling": entry.has_provisional_scheduling,
        "revisions": [
            {
                "revision_id": item.reference.revision_id,
                "revision_digest": item.reference.revision_digest,
                "home_team_id": item.home_team_id,
                "away_team_id": item.away_team_id,
                "kickoff_state": item.kickoff_state,
                "kickoff_precision": item.kickoff_precision,
                "kickoff_utc": item.kickoff_utc,
                "kickoff_local_text": item.kickoff_local_text,
                "fixture_status": item.fixture_status,
            }
            for item in entry.revision_facts
        ],
    }
    if isinstance(entry, CandidateManifestEntryV2):
        result["schedule_relation"] = entry.schedule_relation.value
    return result


def _rule_json(rule: OperatorPublicationRule) -> dict[str, object]:
    return {
        "publication_id": rule.publication_id,
        "publisher_id": rule.publisher_id,
        "publication_type": rule.publication_type,
        "layers": list(rule.supported_layers),
        "url": rule.example_url,
    }


def _result(
    arguments: argparse.Namespace,
    result: dict[str, object],
    *,
    exit_code: int = 0,
) -> int:
    if getattr(arguments, "as_json", False):
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    else:
        print("Mode: RESEARCH_ONLY")
        print(f"Status: {result.get('status', 'READY')}")
        for key, label in (
            ("base_assessment_digest", "F01 v2 base"),
            ("scope_id", "Scope"),
            ("candidate_manifest_digest", "Manifest"),
            ("attestation_id", "Attestation"),
            ("artifact_digest", "Artifact"),
            ("assessment_digest", "F01 v3"),
            ("freeze_digest", "F06 freeze"),
            ("reason", "Reason"),
            ("freeze_reason", "F06 reason"),
        ):
            value = result.get(key)
            if value is not None:
                print(f"{label}: {value}")
        scope_outcomes = result.get("scope_outcomes")
        if isinstance(scope_outcomes, list):
            for item in scope_outcomes:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("league"), str)
                    and isinstance(item.get("coverage"), str)
                ):
                    print(f"{item['league']}: {item['coverage']}")
    return exit_code

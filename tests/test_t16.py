from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from matchvet.artifacts import ArtifactRecord, ArtifactStore
from matchvet.matchweek import AppendixDisposition, MembershipState
from matchvet.store import open_store
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, BettingPreference
from matchvet.t15 import CandidateRole, CandidateStatus, MatchDecision, PolicyStatus
from matchvet.t16 import MatchweekAudit, build_matchweek_audit


def _preference_rows(
    *,
    rejected_reason: str | None = None,
    correlation_group: str | None = "goals",
) -> tuple[SimpleNamespace, ...]:
    rows: list[SimpleNamespace] = []
    for index, preference in enumerate(DEFAULT_PREFERENCE_CATALOG):
        rejected = rejected_reason is not None and index > 0
        reasons: tuple[str, ...] = (
            (rejected_reason,) if rejected and rejected_reason is not None else ()
        )
        gates: tuple[dict[str, object], ...] = tuple(
            {
                "gate_id": f"G{gate_index}",
                "name": f"gate-{gate_index}",
                "status": "PASS" if not rejected else "FAIL",
                "passed": not rejected,
                "reason_codes": reasons,
                "details": {},
            }
            for gate_index in range(9)
        )

        def candidate_to_dict(
            preference: BettingPreference = preference,
            rejected: bool = rejected,
            reasons: tuple[str, ...] = reasons,
            gates: tuple[dict[str, object], ...] = gates,
        ) -> dict[str, object]:
            return {
                "preference": preference.to_dict(),
                "status": "REJECT" if rejected else "QUALIFIED",
                "role": "NONE",
                "rejection_reasons": reasons,
                "gates": gates,
                "estimated_probability": None if rejected else 0.78,
                "conservative_probability": None if rejected else 0.70,
                "uncertainty_width": None if rejected else 0.08,
                "data_quality": None if rejected else 0.90,
                "model_agreement": None if rejected else 0.88,
                "failure_risk": None if rejected else 0.18,
            }

        review = SimpleNamespace(
            failure_case="A late role change could invalidate the line.",
            materiality=0.18,
            represented_in_uncertainty=True,
            supporting_evidence_ids=(f"failure-{preference.preference_id}",),
            veto=False,
            downgrade=False,
            complete=True,
        )
        rows.append(
            SimpleNamespace(
                preference=preference,
                status=CandidateStatus.REJECT if rejected else CandidateStatus.QUALIFIED,
                role=CandidateRole.NONE,
                rejection_reasons=reasons,
                selection_strength_reasons=(),
                gates=gates,
                estimated_probability=None if rejected else 0.78,
                conservative_probability=None if rejected else 0.70,
                loss_risk_upper=None if rejected else 0.20,
                push_probability=0.10 if "PUSH" in preference.possible_results else 0.0,
                uncertainty_width=None if rejected else 0.08,
                data_quality=None if rejected else 0.90,
                model_agreement=None if rejected else 0.88,
                model_sensitivity=None if rejected else 0.10,
                historical_reliability=None if rejected else 0.86,
                failure_risk=None if rejected else 0.18,
                baseline={
                    "win_probability": 0.55,
                    "loss_probability": 0.35,
                    "push_probability": 0.10,
                    "hierarchical_key": preference.preference_id,
                    "structural_trivial": False,
                    "match_specific_lift": 0.23,
                    "contract": preference.to_dict(),
                },
                adversarial_review=review,
                selection_components={"conservative_probability": 0.70},
                selection_strength=None if rejected else 0.81 - index / 1000,
                selection_strength_interval=None if rejected else (0.77, 0.84),
                rank=None if rejected else index + 1,
                correlation_group=correlation_group if not rejected else None,
                supporting_case="The frozen evidence supports this exact line.",
                explanatory=True,
                to_dict=candidate_to_dict,
            )
        )
    return tuple(rows)


def _target(fixture_id: str = "fixture-a") -> SimpleNamespace:
    return SimpleNamespace(
        matchweek_id="mw-2026-09-18",
        cutoff_id="cutoff-a",
        fixture_id=fixture_id,
        cutoff_utc="2026-09-18T12:00:00+00:00",
        kickoff_utc="2026-09-18T20:00:00+00:00",
        home_team_id="home-a",
        away_team_id="away-a",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
        fixture_status="SCHEDULED",
        to_dict=lambda: {
            "fixture_id": fixture_id,
            "matchweek_id": "mw-2026-09-18",
            "kickoff_utc": "2026-09-18T20:00:00+00:00",
            "home_team_id": "home-a",
            "away_team_id": "away-a",
            "competition_name": "Premier League",
        },
    )


def _state(fixture_id: str = "fixture-a") -> SimpleNamespace:
    return SimpleNamespace(
        target=_target(fixture_id),
        state_id=f"state-{fixture_id}",
        state_digest=f"digest-{fixture_id}",
        source_assertions=(SimpleNamespace(fact_id=f"fact-{fixture_id}"),),
        post_cutoff_assertions=(),
        gaps=(),
        conflicts=(),
        reproducibility={"source_snapshot_digest": f"snapshot-{fixture_id}"},
        to_dict=lambda: {
            "state_id": f"state-{fixture_id}",
            "state_digest": f"digest-{fixture_id}",
            "source_assertions": [{"fact_id": f"fact-{fixture_id}"}],
            "post_cutoff_assertions": [],
            "gaps": [],
            "conflicts": [],
            "reproducibility": {"source_snapshot_digest": f"snapshot-{fixture_id}"},
        },
    )


def _result(
    fixture_id: str = "fixture-a",
    *,
    decision: MatchDecision = MatchDecision.PLAY,
    policy_status: PolicyStatus = PolicyStatus.PRODUCTION_PROMOTED,
    rejected_reason: str | None = None,
    secondary: bool = True,
) -> SimpleNamespace:
    rows = _preference_rows(rejected_reason=rejected_reason)
    primary = None if decision is not MatchDecision.PLAY else rows[0]
    if primary is not None:
        primary.role = CandidateRole.PRIMARY_RECOMMENDATION
        primary.status = CandidateStatus.PRIMARY_RECOMMENDATION
    secondaries = () if not secondary or primary is None else (rows[1],)
    if secondaries:
        secondaries[0].role = CandidateRole.CORRELATED_SECONDARY_FIT
        secondaries[0].status = CandidateStatus.CORRELATED_SECONDARY_FIT
    return SimpleNamespace(
        target=_target(fixture_id),
        policy_version="policy-v1",
        policy_status=policy_status,
        decision=decision,
        preference_results=rows,
        policy_digest="policy-digest",
        evidence_state_digest=f"digest-{fixture_id}",
        primary_recommendation=primary,
        secondary_fits=secondaries,
        research_primary_candidate=None
        if policy_status is PolicyStatus.PRODUCTION_PROMOTED
        else rows[0],
        research_secondary_candidates=()
        if policy_status is PolicyStatus.PRODUCTION_PROMOTED
        else (rows[1],),
        avoid_reason=("NO_PREFERENCE_PASSED_ABSOLUTE_GATES" if rejected_reason else None),
        audit_digest=f"vetting-{fixture_id}",
        to_dict=lambda: {"decision": decision.value, "policy_status": policy_status.value},
    )


@dataclass(frozen=True)
class _Membership:
    subject_id: str
    target_match: bool = True
    membership_state: MembershipState = MembershipState.INCLUDED
    digest: str = "membership-digest"
    controlling_revision_id: str = "revision-a"
    controlling_revision_digest: str = "revision-digest"
    original_kickoff_utc: str = "2026-09-18T20:00:00+00:00"

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "target_match": self.target_match,
            "membership_state": self.membership_state.value,
            "digest": self.digest,
            "controlling_revision_id": self.controlling_revision_id,
            "controlling_revision_digest": self.controlling_revision_digest,
            "original_kickoff_utc": self.original_kickoff_utc,
        }


def _metadata() -> dict[str, object]:
    return {
        "matchweek_id": "mw-2026-09-18",
        "window_start_local": "2026-09-18T00:00:00+01:00",
        "window_end_local": "2026-09-22T00:00:00+01:00",
        "target_league_set_version": "2026-27-target-leagues-v1",
        "model_version": "model-v1",
        "feature_version": "features-v1",
        "research_rules_version": "research-v1",
        "data_snapshot_digest": "a" * 64,
        "software_commit": "b" * 40,
    }


def _audit(
    *, result: SimpleNamespace | None = None, run_status: object | None = None
) -> MatchweekAudit:
    selected = result or _result()
    return build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=(_Membership(selected.target.fixture_id),),
        vetting={selected.target.fixture_id: selected},
        evidence_states={selected.target.fixture_id: _state(selected.target.fixture_id)},
        predictions={selected.target.fixture_id: {}},
        reproducibility=_metadata(),
        run_status=run_status,
    )


def test_complete_audit_retains_every_target_and_all_37_preference_results() -> None:
    audit = _audit()

    assert audit.publication_state.value == "COMPLETE"
    assert audit.coverage["included_target_matches"] == 1
    assert len(audit.matches) == 1
    match = audit.matches[0]
    preference_results = match["preference_results"]
    assert isinstance(preference_results, list)
    assert len(preference_results) == 37
    assert match["evidence_identities"]
    first_result = preference_results[0]
    assert isinstance(first_result, dict)
    gates = first_result["gates"]
    assert isinstance(gates, list)
    assert len(gates) == 9
    risk_assessment = first_result["risk_assessment"]
    assert isinstance(risk_assessment, dict)
    assert risk_assessment["failure_case"]
    assert audit.reproducibility["software_commit"] == "b" * 40
    assert audit.audit_id


def test_audit_retains_nested_prediction_distributions_and_version_metadata() -> None:
    preference_id = next(iter(DEFAULT_PREFERENCE_CATALOG)).preference_id
    audit = build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=(_Membership("fixture-a"),),
        vetting={"fixture-a": _result()},
        evidence_states={"fixture-a": _state()},
        predictions={
            "fixture-a": {
                "predictions": {
                    "FULL_TIME_GOALS": {
                        "model_version": "model-v2",
                        "model_digest": "c" * 64,
                        "calibration_version": "calibration-v2",
                        "prediction_digest": "d" * 64,
                        "settlement_distributions": {
                            preference_id: {"WIN": 0.78, "LOSS": 0.12, "PUSH": 0.10}
                        },
                        "probability_intervals": {preference_id: {"lower": 0.70, "upper": 0.84}},
                    }
                }
            }
        },
        reproducibility=_metadata(),
    )

    preference_results = audit.matches[0]["preference_results"]
    assert isinstance(preference_results, list)
    first_result = preference_results[0]
    assert isinstance(first_result, dict)
    assert first_result["settlement_distribution"] == {
        "WIN": 0.78,
        "LOSS": 0.12,
        "PUSH": 0.10,
    }
    uncertainty = first_result["uncertainty"]
    assert isinstance(uncertainty, dict)
    prediction = uncertainty["prediction"]
    assert isinstance(prediction, dict)
    assert prediction["model_version"] == "model-v2"
    versions = audit.reproducibility["prediction_versions"]
    assert isinstance(versions, dict)
    assert versions["fixture-a"]


def test_production_report_has_required_play_card_and_correlated_secondary() -> None:
    from matchvet.t16 import render_markdown_report

    audit = _audit()
    markdown = render_markdown_report(audit)

    for text in (
        "Primary Recommendation",
        "Correlated Secondary Fits",
        "Estimated Probability",
        "Conservative Probability",
        "Data Quality",
        "Model Agreement",
        "strongest credible failure case",
        "why it ranked above alternatives",
        "Audit:",
    ):
        assert text in markdown


def test_research_only_report_never_uses_production_decision_language() -> None:
    from matchvet.t16 import render_markdown_report

    result = _result(
        decision=MatchDecision.RESEARCH_ONLY,
        policy_status=PolicyStatus.RESEARCH_ONLY,
    )
    markdown = render_markdown_report(_audit(result=result))

    assert "RESEARCH ONLY" in markdown
    assert "NOT A RECOMMENDATION" in markdown
    assert "Primary Recommendation" not in markdown
    assert "PLAY" not in markdown
    assert "AVOID MATCH" not in markdown

    from matchvet.t16 import build_report_payload

    report = build_report_payload(_audit(result=result))
    report_matches = report["matches"]
    assert isinstance(report_matches, tuple)
    report_match = report_matches[0]
    assert isinstance(report_match, dict)
    assert "primary_recommendation" not in report_match
    assert "research_candidate" in report_match


def test_avoid_and_research_avoid_are_compact_and_standardized() -> None:
    from matchvet.t16 import render_markdown_report

    avoid = _audit(
        result=_result(
            decision=MatchDecision.AVOID_MATCH,
            rejected_reason="CONSERVATIVE_PROBABILITY_BELOW_THRESHOLD",
            secondary=False,
        )
    )
    research_avoid = _audit(
        result=_result(
            decision=MatchDecision.RESEARCH_AVOID,
            policy_status=PolicyStatus.RESEARCH_ONLY,
            rejected_reason="PROBABILITY_UNCERTAINTY_ABOVE_THRESHOLD",
            secondary=False,
        )
    )

    avoid_markdown = render_markdown_report(avoid)
    research_markdown = render_markdown_report(research_avoid)
    assert "AVOID MATCH" in avoid_markdown
    assert "INSUFFICIENT_PROBABILITY" in avoid_markdown
    assert "RESEARCH AVOID" in research_markdown
    assert "NOT A RECOMMENDATION" in research_markdown
    assert "AVOID MATCH" not in research_markdown


def test_withdrawn_fixture_is_reported_as_void_without_a_play_or_avoid() -> None:
    from matchvet.t16 import render_markdown_report

    membership = _Membership("fixture-a")
    appendix = (
        SimpleNamespace(
            fixture_id="fixture-a",
            subject_id="fixture-a",
            disposition=AppendixDisposition.WITHDRAWN,
            settlement_result="VOID",
            event_kind="POSTPONED",
            reason="The fixture was postponed after cutoff.",
            to_dict=lambda: {
                "fixture_id": "fixture-a",
                "disposition": "WITHDRAWN",
                "settlement_result": "VOID",
            },
        ),
    )
    from matchvet.t16 import build_matchweek_audit

    audit = build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=(membership,),
        vetting=SimpleNamespace(matches=(_result(),)),
        evidence_states={"fixture-a": _state()},
        predictions={"fixture-a": {}},
        appendix=appendix,
        reproducibility=_metadata(),
    )
    match = audit.matches[0]
    assert match["outcome"] == "WITHDRAWN"
    assert match["settlement_result"] == "VOID"
    rendered = render_markdown_report(audit)
    assert "Withdrawn / VOID" in rendered
    assert "Primary Recommendation" not in rendered


def test_freeze_appendix_explicit_void_and_reproducibility_aliases_are_retained() -> None:
    from matchvet.t16 import build_matchweek_audit, render_markdown_report

    appendix = (
        SimpleNamespace(
            fixture_id="fixture-a",
            subject_id="fixture-a",
            disposition=AppendixDisposition.WITHDRAWN,
            to_dict=lambda: {
                "fixture_id": "fixture-a",
                "disposition": "WITHDRAWN",
            },
        ),
    )
    freeze = SimpleNamespace(
        memberships=(_Membership("fixture-a"),),
        appendix=appendix,
    )
    audit = build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=freeze,
        vetting=SimpleNamespace(matches=(_result(),)),
        evidence_states={"fixture-a": _state()},
        predictions={"fixture-a": {}},
        withdrawn_fixture_ids=("fixture-a",),
        void_fixture_ids=("fixture-a",),
        reproducibility={
            **_metadata(),
            "model_ensemble_version": "ensemble-v1",
            "data_snapshot_id": "snapshot-id",
            "retrieval_cutoff_id": "retrieval-cutoff-id",
            "matchweek_membership_manifest_digest": "membership-manifest-digest",
            "matchweek_snapshot_digest": "matchweek-snapshot-digest",
            "canonical_timestamp_rule": "UTC event timestamps; deterministic sort by fixture_id",
        },
    )

    assert audit.matches[0]["outcome"] == "WITHDRAWN"
    assert audit.matches[0]["settlement_result"] == "VOID"
    assert audit.reproducibility["model_ensemble_version"] == "ensemble-v1"
    assert audit.reproducibility["data_snapshot_id"] == "snapshot-id"
    assert audit.reproducibility["retrieval_cutoff_id"] == "retrieval-cutoff-id"
    assert audit.reproducibility["matchweek_membership_manifest_digest"] == (
        "membership-manifest-digest"
    )
    assert "Withdrawn / VOID" in render_markdown_report(audit)


def test_indeterminate_membership_is_visible_without_a_production_decision() -> None:
    from matchvet.t16 import build_matchweek_audit, render_markdown_report

    audit = build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=(
            _Membership("fixture-a"),
            _Membership(
                "fixture-unknown",
                target_match=False,
                membership_state=MembershipState.INDETERMINATE,
            ),
        ),
        vetting={"fixture-a": _result()},
        evidence_states={"fixture-a": _state()},
        predictions={"fixture-a": {}},
        reproducibility=_metadata(),
    )

    assert audit.coverage["indeterminate_memberships"] == ["fixture-unknown"]
    rendered = render_markdown_report(audit)
    assert "INDETERMINATE" in rendered
    assert "fixture-unknown" in rendered


def test_incomplete_run_cannot_publish_or_render_a_completed_decision() -> None:
    from matchvet.t16 import T16IncompleteError, publish_matchweek_audit, render_markdown_report

    incomplete = _audit(
        run_status=SimpleNamespace(
            state="INCOMPLETE",
            completed_work_units=4,
            total_work_units=7,
            last_checkpoint="frozen_evidence_state_construction",
        )
    )
    rendered = render_markdown_report(incomplete)
    assert "INCOMPLETE" in rendered
    assert "NO DECISION" in rendered
    assert "Primary Recommendation" not in rendered
    with pytest.raises(T16IncompleteError):
        publish_matchweek_audit(incomplete, store=None)


def test_missing_target_evaluation_is_an_incomplete_no_decision_audit() -> None:
    from matchvet.t16 import build_matchweek_audit, render_markdown_report

    audit = build_matchweek_audit(
        matchweek_id="mw-2026-09-18",
        memberships=(_Membership("fixture-a"),),
        vetting={},
        evidence_states={},
        reproducibility=_metadata(),
    )

    assert audit.publication_state.value == "INCOMPLETE"
    target = audit.matches[0]["target"]
    assert isinstance(target, dict)
    assert target["fixture_id"] == "fixture-a"
    assert audit.matches[0]["decision"] == "NO DECISION"
    rendered = render_markdown_report(audit)
    assert "INCOMPLETE" in rendered
    assert "NO DECISION" in rendered
    assert "Primary Recommendation" not in rendered


def test_audit_json_is_schema_versioned_and_deterministic() -> None:
    first = _audit()
    second = _audit()

    assert first.to_bytes() == second.to_bytes()
    payload = json.loads(first.to_bytes())
    assert payload["schema_version"] == 1
    assert payload["schema"] == "matchvet.matchweek.audit"
    assert payload["audit_digest"] == first.audit_digest
    assert payload["preference_set"]["count"] == 37

    from matchvet.t16 import render_markdown_report

    assert render_markdown_report(first) == render_markdown_report(second)


def test_publish_inspect_and_history_use_complete_publication_marker(tmp_path: Path) -> None:
    from matchvet.t16 import (
        history,
        inspect_match,
        publish_matchweek_audit,
        read_report,
    )

    database_path = tmp_path / "private" / "matchvet.sqlite3"
    private_root = tmp_path / "private"
    private_root.mkdir()
    audit = _audit()
    with open_store(database_path, private_root=private_root) as store:
        publication = publish_matchweek_audit(audit, store=store, run_id="run-a")
        assert publication.publication_state.value == "COMPLETE"
        report = read_report(database_path, private_root=private_root)
        inspected = inspect_match(database_path, "fixture-a", private_root=private_root)
        entries = history(database_path, private_root=private_root)

    audit_reference = report["audit_reference"]
    assert isinstance(audit_reference, dict)
    assert audit_reference["audit_id"] == audit.audit_id
    assert inspected["fixture_id"] == "fixture-a"
    preference_results = inspected["preference_results"]
    assert isinstance(preference_results, list)
    assert len(preference_results) == 37
    membership = inspected["membership"]
    assert isinstance(membership, dict)
    membership_id = membership["subject_id"]
    assert isinstance(membership_id, str)
    assert inspect_match(database_path, membership_id, private_root=private_root)["fixture_id"] == (
        "fixture-a"
    )
    assert entries[0]["audit_state"] == "COMPLETE"
    assert entries[0]["run_id"] == "run-a"
    assert entries[0]["grading_state"] == "NOT_STARTED"
    assert entries[0]["export_state"] == "OUT_OF_SCOPE"
    assert entries[0]["backup_state"] == "OUT_OF_SCOPE"


@pytest.mark.failure_injection
def test_interrupted_audit_publication_stays_invisible_until_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.t16 import T16Error, history, publish_matchweek_audit, read_audit

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    original = ArtifactStore.publish_artifact
    calls = 0

    def interrupt_before_marker(
        self: ArtifactStore,
        content: bytes,
        media_type: str,
        *,
        expected_digest: str | None = None,
        retention_class: str = "PROTECTED",
    ) -> ArtifactRecord:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected interruption before complete marker")
        return original(
            self,
            content,
            media_type,
            expected_digest=expected_digest,
            retention_class=retention_class,
        )

    audit = _audit()
    with open_store(database_path, private_root=private_root) as store:
        monkeypatch.setattr(ArtifactStore, "publish_artifact", interrupt_before_marker)
        with pytest.raises(T16Error, match="Atomic T16 publication failed"):
            publish_matchweek_audit(audit, store=store)
        assert history(database_path, private_root=private_root) == []
        monkeypatch.setattr(ArtifactStore, "publish_artifact", original)
        publication = publish_matchweek_audit(audit, store=store)

    assert publication.audit_digest == audit.audit_digest
    assert read_audit(database_path, private_root=private_root).audit_digest == audit.audit_digest
    assert len(history(database_path, private_root=private_root)) == 1


def test_history_is_empty_without_publications_and_does_not_mutate_store(tmp_path: Path) -> None:
    from matchvet.t16 import history

    database_path = tmp_path / "private" / "matchvet.sqlite3"
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(database_path, private_root=private_root):
        before = database_path.stat().st_mtime_ns
        assert history(database_path, private_root=private_root) == []
        assert database_path.stat().st_mtime_ns == before


def test_cli_report_inspect_and_history_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from matchvet import cli
    from matchvet.t16 import publish_matchweek_audit

    database_path = tmp_path / "private" / "matchvet.sqlite3"
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(database_path, private_root=private_root) as store:
        publish_matchweek_audit(_audit(), store=store, run_id="run-cli")
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)

    assert cli.main(["report", "--store", str(database_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "matchvet.matchweek.report"
    assert report["audit_reference"]["audit_id"]

    assert cli.main(["inspect", "fixture-a", "--store", str(database_path), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert len(inspected["preference_results"]) == 37

    assert cli.main(["history", "--store", str(database_path), "--json"]) == 0
    history_payload = json.loads(capsys.readouterr().out)
    assert history_payload[0]["audit_state"] == "COMPLETE"

    assert cli.main(["report", "--store", str(database_path)]) == 0
    assert "# matchvet report" in capsys.readouterr().out

    assert cli.main(["report", "--audit", "--store", str(database_path)]) == 0
    audit_payload = json.loads(capsys.readouterr().out)
    assert audit_payload["schema"] == "matchvet.matchweek.audit"


def test_cli_incomplete_report_is_nonzero_and_never_exposes_production_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from matchvet import cli

    database_path = tmp_path / "private" / "matchvet.sqlite3"
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(database_path, private_root=private_root):
        pass
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)
    result = cli.main(["report", "--store", str(database_path), "--json"])
    output = capsys.readouterr().out
    assert result == 1
    assert json.loads(output)["status"] in {"INCOMPLETE", "REFUSED"}
    assert "PLAY" not in output
    assert "AVOID MATCH" not in output

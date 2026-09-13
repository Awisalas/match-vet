from __future__ import annotations

from pathlib import Path

import pytest

from matchvet.evidence import (
    CutoffEligibility,
    EvidenceAssertionInput,
    EvidenceClass,
    EvidenceIntegrityError,
    EvidencePolicyError,
    EvidenceRecorder,
    EvidenceState,
    EvidenceType,
    EvidenceValidationError,
    IndependentOrigin,
    SourceCaptureInput,
    SourceIdentity,
    SourceStatus,
    SubjectKind,
    authority_rank,
)
from matchvet.store import CanonicalIdentifier, Store, open_store


def _source(
    source_key: str,
    *,
    source_class: str = "OFFICIAL_CLUB",
    retention_status: str = "CITATION_ONLY",
    allowed_use: str | None = None,
) -> SourceIdentity:
    selected_allowed_use = allowed_use or (
        "RESTRICTED_PRIVATE"
        if retention_status in {"RETAIN_PRIVATE", "RETAIN_REUSABLE"}
        else "CITATION_ONLY"
    )
    return SourceIdentity(
        source_key=source_key,
        canonical_name=source_key.replace("-", " ").title(),
        owner=source_key,
        source_class=source_class,
        access_method="MANUAL_CITATION",
        base_locator=f"https://{source_key}.example/",
        allowed_use=selected_allowed_use,
        retention_status=retention_status,
        redistributable=False,
        terms_reference="recorded test terms",
    )


def _origin(origin_key: str) -> IndependentOrigin:
    return IndependentOrigin(
        origin_key=origin_key,
        organization=origin_key.replace("-", " ").title(),
        classification="DIRECT_ORIGIN",
    )


def _canonical_fixture(store: Store, private_root: Path) -> tuple[str, str, str]:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        league_by_key,
    )
    from matchvet.ingestion import (
        SourceCaptureInput as StructuredCaptureInput,
    )

    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n"
    )
    dataset = FootballDataCSVParser().parse(
        content,
        league=league_by_key("premier_league"),
        season="2026-27",
    )
    importer = FixtureHistoryImporter(store, private_root=private_root)
    importer.import_dataset(
        dataset,
        content,
        StructuredCaptureInput(
            source_url="https://www.football-data.co.uk/mmz4281/2627/E0.csv",
            retrieved_at_utc="2026-09-13T08:00:00+00:00",
            observed_terms="restricted private",
            content_type="text/csv",
        ),
    )
    fixture = importer.fixtures()[0]
    return fixture.fixture_id, fixture.home_team_id, fixture.away_team_id


def _capture(
    source_key: str,
    origin_key: str,
    locator_suffix: str,
    *,
    source_class: str = "OFFICIAL_CLUB",
    retrieved_at_utc: str = "2026-09-13T10:00:00+00:00",
    published_at_utc: str | None = "2026-09-13T09:00:00+00:00",
    retention_status: str = "CITATION_ONLY",
    content: bytes | None = None,
    capture_key: str | None = None,
) -> SourceCaptureInput:
    return SourceCaptureInput(
        source=_source(
            source_key,
            source_class=source_class,
            retention_status=retention_status,
        ),
        origin=_origin(origin_key),
        locator=f"https://{source_key}.example/{locator_suffix}",
        retrieved_at_utc=retrieved_at_utc,
        published_at_utc=published_at_utc,
        content=content,
        capture_key=capture_key or locator_suffix,
    )


def test_retained_and_citation_only_captures_are_distinct_and_auditable(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Ada Manager", role="MANAGER")
        retained = recorder.ingest(
            SourceCaptureInput(
                source=_source(
                    "official-club",
                    source_class="OFFICIAL_CLUB",
                    retention_status="RETAIN_PRIVATE",
                ),
                origin=_origin("official-club"),
                locator="https://official-club.example/news/1",
                retrieved_at_utc="2026-09-13T10:00:00+00:00",
                published_at_utc="2026-09-13T09:00:00+00:00",
                content=b"allowed retained capture",
                capture_key="news-1",
            ),
            [
                EvidenceAssertionInput(
                    subject_kind=SubjectKind.PERSON,
                    subject_id=person_id,
                    evidence_type=EvidenceType.MANAGER_CHANGE,
                    predicate="role",
                    state=EvidenceState.OBSERVED,
                    value={"role": "manager"},
                    evidence_class=EvidenceClass.IMPORTANT,
                    assertion_key="role",
                )
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )
        citation = recorder.ingest(
            SourceCaptureInput(
                source=_source("specialist-report", source_class="SPECIALIST_REPORTING"),
                origin=_origin("specialist-origin"),
                locator="https://specialist.example/report/1",
                retrieved_at_utc="2026-09-13T11:00:00+00:00",
                published_at_utc="2026-09-13T10:30:00+00:00",
                capture_key="report-1",
                citation_note="Named report retained as citation only.",
            ),
            [
                EvidenceAssertionInput(
                    subject_kind=SubjectKind.PERSON,
                    subject_id=person_id,
                    evidence_type=EvidenceType.MANAGER_CHANGE,
                    predicate="role",
                    state=EvidenceState.OBSERVED,
                    value={"role": "manager"},
                    assertion_key="role",
                )
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )

        assert retained.capture.capture_kind == "RETAINED"
        assert retained.capture.artifact_digest is not None
        assert citation.capture.capture_kind == "CITATION_ONLY"
        assert citation.capture.artifact_digest is None
        assert citation.capture.content_sha256 is None
        assert citation.assertions[0].cutoff_eligibility == "CUTOFF_VALID"
    assert citation.assertions[0].source_class == "SPECIALIST_REPORTING"


def test_observed_absent_and_unknown_are_not_interchangeable(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Bea Player", role="PLAYER")
        capture = SourceCaptureInput(
            source=_source("club-status"),
            origin=_origin("club-status"),
            locator="https://club-status.example/availability",
            retrieved_at_utc="2026-09-13T10:00:00+00:00",
            capture_key="availability",
        )
        result = recorder.ingest(
            capture,
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    EvidenceState.OBSERVED,
                    "AVAILABLE",
                    assertion_key="observed",
                ),
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.SUSPENSION,
                    "status",
                    EvidenceState.ABSENT,
                    affirmative_basis="The official disciplinary list names no suspension.",
                    assertion_key="absent",
                ),
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.INJURY,
                    "status",
                    EvidenceState.UNKNOWN,
                    unknown_reason="No suitable current medical statement was found.",
                    assertion_key="unknown",
                ),
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )

        assert [item.state for item in result.assertions] == [
            EvidenceState.OBSERVED,
            EvidenceState.ABSENT,
            EvidenceState.UNKNOWN,
        ]
        assert result.assertions[1].value is None
        assert result.assertions[2].unknown_reason is not None
        unknown = recorder.record_unknown(
            subject_kind=SubjectKind.PERSON,
            subject_id=person_id,
            evidence_type=EvidenceType.REFEREE_CONTEXT,
            predicate="history",
            reason="No eligible source was available.",
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )
        assert unknown.state is EvidenceState.UNKNOWN
        important_unknown = recorder.record_unknown(
            subject_kind=SubjectKind.PERSON,
            subject_id=person_id,
            evidence_type=EvidenceType.INJURY,
            predicate="status",
            reason="No suitable current medical statement was found.",
        )
        assert important_unknown.evidence_class is EvidenceClass.IMPORTANT


def test_missing_publication_time_is_valid_before_cutoff_but_indeterminate_after(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Casey Player", role="PLAYER")
        capture = SourceCaptureInput(
            source=_source("missing-published"),
            origin=_origin("missing-published"),
            locator="https://missing-published.example/item",
            retrieved_at_utc="2026-09-13T10:00:00+00:00",
            capture_key="item",
        )
        before = recorder.ingest(
            capture,
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                )
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )
        after = recorder.ingest(
            SourceCaptureInput(
                source=capture.source,
                origin=capture.origin,
                locator=capture.locator,
                retrieved_at_utc="2026-09-13T13:00:00+00:00",
                capture_key="item-after",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                )
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )

        assert before.assertions[0].cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
        assert after.assertions[0].cutoff_eligibility is CutoffEligibility.INDETERMINATE


def test_specialist_reporting_is_context_only_and_rejected_source_foundations_fail(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Drew Manager", role="MANAGER")
        specialist = recorder.ingest(
            SourceCaptureInput(
                source=_source("specialist-context", source_class="SPECIALIST_REPORTING"),
                origin=_origin("specialist-context"),
                locator="https://specialist-context.example/news",
                retrieved_at_utc="2026-09-13T10:00:00+00:00",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.TACTICAL_CONTEXT,
                    "shape",
                    value="4-3-3",
                )
            ],
            cutoff_utc="2026-09-13T12:00:00+00:00",
        )

        assert specialist.assertions[0].evidence_class is EvidenceClass.CONTEXT
        with pytest.raises(Exception, match="rejected evidence foundation"):
            SourceIdentity(
                source_key="transfermarkt",
                canonical_name="Rejected",
                owner="Rejected",
                source_class="SPECIALIST_REPORTING",
                access_method="MANUAL_CITATION",
                base_locator="https://transfermarkt.example/",
                allowed_use="CITATION_ONLY",
                retention_status="CITATION_ONLY",
                redistributable=False,
                terms_reference="test",
            )


def test_evidence_attaches_only_to_canonical_fixture_team_and_person(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        fixture_id, home_team_id, _away_team_id = _canonical_fixture(store, tmp_path)
        person_id = recorder.register_person("Evan Referee", role="REFEREE")
        result = recorder.ingest(
            _capture("canonical-attachments", "canonical-attachments", "facts"),
            [
                EvidenceAssertionInput(
                    SubjectKind.FIXTURE,
                    fixture_id,
                    EvidenceType.REFEREE_APPOINTMENT,
                    "referee",
                    value={"person_id": person_id},
                ),
                EvidenceAssertionInput(
                    SubjectKind.TEAM,
                    home_team_id,
                    EvidenceType.ROTATION,
                    "plan",
                    value={"rested": True},
                ),
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.REFEREE_CONTEXT,
                    "style",
                    value={"discipline": "strict"},
                ),
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.SUSPENSION,
                    "status",
                    value="CLEAR",
                ),
                EvidenceAssertionInput(
                    SubjectKind.TEAM,
                    home_team_id,
                    EvidenceType.EXPECTED_LINEUP,
                    "players",
                    value=[person_id],
                ),
                EvidenceAssertionInput(
                    SubjectKind.TEAM,
                    home_team_id,
                    EvidenceType.REGIME_CHANGE,
                    "manager",
                    value={"state": "new-manager"},
                ),
            ],
        )

        assert {item.subject_kind for item in result.assertions} == {
            SubjectKind.FIXTURE,
            SubjectKind.TEAM,
            SubjectKind.PERSON,
        }
        assert len(recorder.people()) == 1
        with pytest.raises(EvidenceValidationError, match="existing canonical"):
            recorder.ingest(
                _capture("unknown-attachment", "unknown-attachment", "facts"),
                [
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        CanonicalIdentifier.new("person"),
                        EvidenceType.INJURY,
                        "status",
                        value="OUT",
                    )
                ],
            )


def test_official_hierarchy_wins_without_overwriting_contextual_assertions(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Femi Player", role="PLAYER")
        official = recorder.ingest(
            _capture(
                "official-injury",
                "official-injury",
                "statement",
                source_class="OFFICIAL_CLUB",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.INJURY,
                    "status",
                    value="OUT",
                    assertion_key="official",
                )
            ],
        )
        specialist = recorder.ingest(
            _capture(
                "specialist-injury",
                "specialist-injury",
                "report",
                source_class="SPECIALIST_REPORTING",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.INJURY,
                    "status",
                    value="AVAILABLE",
                    assertion_key="specialist",
                )
            ],
        )

        assert authority_rank(EvidenceType.INJURY, "OFFICIAL_CLUB") < authority_rank(
            EvidenceType.INJURY, "SPECIALIST_REPORTING"
        )
        assert (
            recorder.preferred_assertion(
                SubjectKind.PERSON,
                person_id,
                evidence_type=EvidenceType.INJURY,
                predicate="status",
            )
            == official.assertions[0]
        )
        assert specialist.assertions[0].value == "AVAILABLE"
        assert len(recorder.assertions(SubjectKind.PERSON, person_id)) == 2


def test_source_identity_is_immutable_and_cannot_be_reused_differently(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Fatima Player", role="PLAYER")
        recorder.ingest(
            _capture("immutable-source", "immutable-origin", "first"),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.INJURY,
                    "status",
                    value="OUT",
                )
            ],
        )
        mismatched_source = SourceIdentity(
            source_key="immutable-source",
            canonical_name="Changed Source Name",
            owner="immutable-source",
            source_class="OFFICIAL_CLUB",
            access_method="MANUAL_CITATION",
            base_locator="https://immutable-source.example/",
            allowed_use="CITATION_ONLY",
            retention_status="CITATION_ONLY",
            redistributable=False,
            terms_reference="recorded test terms",
        )
        with pytest.raises(EvidenceIntegrityError, match="immutable"):
            recorder.ingest(
                SourceCaptureInput(
                    source=mismatched_source,
                    origin=_origin("immutable-origin"),
                    locator="https://immutable-source.example/second",
                    retrieved_at_utc="2026-09-13T11:00:00+00:00",
                ),
                [
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        person_id,
                        EvidenceType.INJURY,
                        "status",
                        value="AVAILABLE",
                    )
                ],
            )


def test_independent_origin_corroboration_deduplicates_syndicated_reports_and_ingestion(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Grace Player", role="PLAYER")
        repeated = _capture(
            "official-availability",
            "shared-wire-origin",
            "availability",
        )
        first = recorder.ingest(
            repeated,
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                    assertion_key="status",
                )
            ],
        )
        duplicate = recorder.ingest(
            repeated,
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                    assertion_key="status",
                )
            ],
        )
        recorder.ingest(
            _capture(
                "specialist-syndication",
                "shared-wire-origin",
                "availability-copy",
                source_class="SPECIALIST_REPORTING",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                    assertion_key="copy",
                )
            ],
        )
        independent = recorder.ingest(
            _capture(
                "manager-availability",
                "manager-direct-origin",
                "press-conference",
                source_class="OFFICIAL_MANAGER",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                    assertion_key="manager",
                )
            ],
        )

        corroboration = recorder.corroboration(
            SubjectKind.PERSON,
            person_id,
            evidence_type=EvidenceType.AVAILABILITY,
            predicate="status",
            value="DOUBTFUL",
        )
        assert duplicate.from_existing_capture is True
        assert duplicate.assertions == first.assertions
        assert independent.assertions[0].origin_id != first.assertions[0].origin_id
        assert corroboration.independent_origin_count == 2
        assert len(corroboration.assertion_ids) == 3
        assert len(recorder.source_captures()) == 3


def test_conflicts_corrections_and_resolutions_are_append_only(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Hauwa Player", role="PLAYER")
        original = recorder.ingest(
            _capture("club-report-one", "club-origin-one", "availability-one"),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="AVAILABLE",
                    assertion_key="original",
                )
            ],
        )
        conflicting = recorder.ingest(
            _capture("club-report-two", "club-origin-two", "availability-two"),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="OUT",
                    assertion_key="conflicting",
                )
            ],
        )
        assert len(conflicting.conflicts) == 1
        conflict = conflicting.conflicts[0]
        assert conflict.status == "UNRESOLVED"
        assert set(conflict.assertion_ids) == {
            original.assertions[0].assertion_id,
            conflicting.assertions[0].assertion_id,
        }

        resolution = recorder.resolve_conflict(
            conflict.conflict_id,
            original.assertions[0].assertion_id,
            basis=("authority", "freshness"),
            rationale="The direct club statement has the stronger settled authority.",
        )
        assert resolution.selected_assertion_id == original.assertions[0].assertion_id
        assert recorder.conflict_resolutions(conflict.conflict_id) == (resolution,)
        with pytest.raises(EvidenceIntegrityError, match="resolution identity"):
            recorder.resolve_conflict(
                conflict.conflict_id,
                original.assertions[0].assertion_id,
                basis=("authority", "freshness"),
                rationale="A different rationale cannot mutate an append-only resolution.",
            )

        correction = recorder.ingest(
            _capture("club-correction", "club-origin-one", "availability-correction"),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="DOUBTFUL",
                    assertion_key="correction",
                    correction_of=original.assertions[0].assertion_id,
                )
            ],
        )
        chain = recorder.correction_chain(correction.assertions[0].assertion_id)
        all_assertions = recorder.assertions(SubjectKind.PERSON, person_id)
        assert [item.assertion_id for item in chain] == [
            original.assertions[0].assertion_id,
            correction.assertions[0].assertion_id,
        ]
        assert len(all_assertions) == 3
        assert {item.value for item in all_assertions} == {"AVAILABLE", "OUT", "DOUBTFUL"}
        assert len(recorder.conflicts(SubjectKind.PERSON, person_id)) == 2


def test_cutoff_boundary_exposes_post_cutoff_evidence_but_preference_uses_valid_only(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Ife Player", role="PLAYER")
        cutoff = "2026-09-13T12:00:00+00:00"
        exact = recorder.ingest(
            _capture(
                "exact-cutoff",
                "exact-cutoff",
                "statement",
                published_at_utc=cutoff,
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="AVAILABLE",
                    assertion_key="exact",
                )
            ],
            cutoff_utc=cutoff,
        )
        post = recorder.ingest(
            _capture(
                "post-cutoff",
                "post-cutoff",
                "statement",
                retrieved_at_utc="2026-09-13T12:30:00+00:00",
                published_at_utc="2026-09-13T12:01:00+00:00",
            ),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="OUT",
                    assertion_key="post",
                )
            ],
            cutoff_utc=cutoff,
        )

        records = recorder.assertions(
            SubjectKind.PERSON,
            person_id,
            evidence_type=EvidenceType.AVAILABILITY,
            predicate="status",
            cutoff_utc=cutoff,
        )
        assert exact.assertions[0].cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
        assert post.assertions[0].cutoff_eligibility is CutoffEligibility.POST_CUTOFF
        assert {item.cutoff_eligibility for item in records} == {
            CutoffEligibility.CUTOFF_VALID,
            CutoffEligibility.POST_CUTOFF,
        }
        assert (
            recorder.preferred_assertion(
                SubjectKind.PERSON,
                person_id,
                evidence_type=EvidenceType.AVAILABILITY,
                predicate="status",
                cutoff_utc=cutoff,
            )
            == exact.assertions[0]
        )
        cutoff_corroboration = recorder.corroboration(
            SubjectKind.PERSON,
            person_id,
            evidence_type=EvidenceType.AVAILABILITY,
            predicate="status",
            value="AVAILABLE",
            cutoff_utc=cutoff,
        )
        assert cutoff_corroboration.independent_origin_count == 1
        assert cutoff_corroboration.assertion_ids == (exact.assertions[0].assertion_id,)


def test_rights_source_status_and_transaction_rollback_are_enforced(
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = EvidenceRecorder(store)
        person_id = recorder.register_person("Jide Player", role="PLAYER")
        with pytest.raises(EvidencePolicyError, match="rights"):
            recorder.ingest(
                _capture(
                    "no-retention",
                    "no-retention",
                    "item",
                    retention_status="DO_NOT_RETAIN",
                    content=b"must not be retained",
                ),
                [
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        person_id,
                        EvidenceType.INJURY,
                        "status",
                        value="OUT",
                    )
                ],
            )
        with pytest.raises(EvidencePolicyError, match="citation-only"):
            SourceCaptureInput(
                source=_source(
                    "specialist-retained",
                    source_class="SPECIALIST_REPORTING",
                    retention_status="RETAIN_PRIVATE",
                ),
                origin=_origin("specialist-retained"),
                locator="https://specialist-retained.example/item",
                retrieved_at_utc="2026-09-13T10:00:00+00:00",
                content=b"specialist content",
            )

        before = recorder.ingest(
            _capture("suspendable", "suspendable", "before"),
            [
                EvidenceAssertionInput(
                    SubjectKind.PERSON,
                    person_id,
                    EvidenceType.AVAILABILITY,
                    "status",
                    value="AVAILABLE",
                )
            ],
        )
        suspended = recorder.suspend_source(
            before.capture.source_id,
            reason="Source identity failed the operator review.",
            observed_at_utc="2026-09-13T11:00:00+00:00",
        )
        assert suspended.status is SourceStatus.SUSPENDED
        assert recorder.source_status_history(before.capture.source_id)[-1] == suspended
        with pytest.raises(EvidencePolicyError, match="suspended"):
            recorder.ingest(
                _capture(
                    "suspendable",
                    "suspendable",
                    "after",
                    retrieved_at_utc="2026-09-13T12:00:00+00:00",
                ),
                [
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        person_id,
                        EvidenceType.AVAILABILITY,
                        "status",
                        value="OUT",
                    )
                ],
            )

        def fail_on_second_assertion(index: int) -> None:
            if index == 2:
                raise RuntimeError("simulated transaction failure")

        rollback_capture = _capture(
            "rollback-source",
            "rollback-origin",
            "rollback",
            retention_status="RETAIN_PRIVATE",
            content=b"rollback capture",
        )
        with pytest.raises(RuntimeError, match="simulated"):
            recorder.ingest(
                rollback_capture,
                [
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        person_id,
                        EvidenceType.INJURY,
                        "status",
                        value="OUT",
                        assertion_key="one",
                    ),
                    EvidenceAssertionInput(
                        SubjectKind.PERSON,
                        person_id,
                        EvidenceType.SUSPENSION,
                        "status",
                        value="SUSPENDED",
                        assertion_key="two",
                    ),
                ],
                failure_hook=fail_on_second_assertion,
            )
        assert not any(item.source_key == "rollback-source" for item in recorder.source_captures())
        assert not recorder.assertions(
            SubjectKind.PERSON,
            person_id,
            evidence_type=EvidenceType.INJURY,
        )

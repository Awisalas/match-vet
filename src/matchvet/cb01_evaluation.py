"""Read-only corrected-cohort admission, preserving the complete CB01 denominator."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.causal_candidate import CAUSAL_CONTRACT
from matchvet.causal_dispatch import (
    InspectedCausalSelection,
    QualifiedCausalSelection,
    resolve_qualified_causal_selection,
)
from matchvet.cb01 import CaseView, DenominatorRow, DenominatorView
from matchvet.cb01_replay import RetainedBootstrapRepository
from matchvet.cb01_schema import MEDIA_TYPES, decode_artifact, normalize_utc
from matchvet.cb01_trust import WitnessBackend
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
from matchvet.f16 import MANIFEST_MEDIA_TYPE as F16_MEDIA_TYPE
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    CORRECTED_RULE,
    FrozenMatchweekResearch,
    MatchweekResearchError,
    MatchweekResearchRepository,
)
from matchvet.store import Store

CHRONOLOGY_VERSION = "0.2.0"
COHORT = "CORRECTED_MATCHWEEK"
CAUSAL_COHORT = "CAUSAL_SELECTION_V2"
LEGACY_COHORT = "LEGACY_PER_MATCH"
LEGACY_CHRONOLOGY = "PER_MATCH_LEGACY"
HISTORICAL_SELECTION_CONTRACT = "postcommit-upper-bound-v1"


class CB01EvaluationError(ValueError):
    """A supplied identity cannot join the corrected evaluation cohort."""

    def __init__(self, message: str, *, denominator: DenominatorView | None = None) -> None:
        super().__init__(message)
        self.denominator = denominator


@dataclass(frozen=True)
class MatchweekEvaluation:
    """Exact frozen cohort plus unavailable cases, with no numerical eligibility claim."""

    policy_digest: str
    common_cutoff_utc: str | None
    selection: FrozenMatchweekResearch | None
    denominator: DenominatorView
    cases: tuple[CaseView, ...]
    cohort: str = COHORT
    chronology_version: str = CHRONOLOGY_VERSION
    unavailable_failure_digests: tuple[str, ...] = ()
    catalog_unavailable_failure_digests: tuple[str, ...] = ()
    selection_contract: str = HISTORICAL_SELECTION_CONTRACT
    methodology_version: str = "0.1.0"
    qualification_status: str = "NOT_QUALIFIED"

    @property
    def included_count(self) -> int:
        return sum(row.membership_state == "INCLUDED" for row in self.denominator.rows)


class MatchweekEvaluationRepository:
    """Count every F06/Profile row; admit exact selected corrected evidence."""

    def __init__(self, store: Store, *, witness_backend: WitnessBackend | None = None) -> None:
        self.store = store
        self.bootstrap = RetainedBootstrapRepository(store, witness_backend=witness_backend)

    def inspect_cohort(
        self,
        freeze_digest: str,
        profile_digest: str,
        policy_digest: str,
        *,
        selection_digest: str | None = None,
        exact_publication_digests: tuple[str, ...] = (),
        exact_attachment_digests: tuple[str, ...] = (),
    ) -> MatchweekEvaluation:
        view = self.inspect_denominator(freeze_digest, profile_digest)
        try:
            return self._inspect_cohort(
                view,
                policy_digest,
                selection_digest,
                exact_publication_digests,
                exact_attachment_digests,
            )
        except (ArtifactError, ValueError) as error:
            raise CB01EvaluationError(str(error), denominator=view) from error

    def inspect_historical_cohort(
        self,
        freeze_digest: str,
        profile_digest: str,
        policy_digest: str,
        *,
        selection_digest: str,
        exact_publication_digests: tuple[str, ...] = (),
        exact_attachment_digests: tuple[str, ...] = (),
    ) -> MatchweekEvaluation:
        """Inspect retained causal history without claiming present qualification."""
        view = self.inspect_denominator(freeze_digest, profile_digest)
        try:
            return self._inspect_cohort(
                view,
                policy_digest,
                selection_digest,
                exact_publication_digests,
                exact_attachment_digests,
                historical_inspection=True,
            )
        except (ArtifactError, ValueError) as error:
            raise CB01EvaluationError(str(error), denominator=view) from error

    def inspect_denominator(self, freeze_digest: str, profile_digest: str) -> DenominatorView:
        """Count exact F06/Profile rows without reading research or witness artifacts."""
        freeze = MatchweekMembershipRepository(self.store).get_by_digest(freeze_digest)
        if freeze is None or freeze.freeze_digest != freeze_digest:
            raise CB01EvaluationError("Exact F06 freeze digest is not retained.")
        profile = PreferenceProfileRepository(self.store).replay(profile_digest)
        return DenominatorView(
            freeze_digest,
            profile_digest,
            tuple(
                DenominatorRow(
                    freeze.freeze_id,
                    membership.membership_id,
                    membership.fixture_id,
                    preference.preference_id,
                    membership.decision.value,
                    "INCOMPLETE_FOR_NOT_ATTEMPTED"
                    if membership.decision.value == "INCLUDED"
                    else "EXCLUDED",
                    None,
                    None,
                    None,
                    (),
                    ("NO_EXACT_SELECTED_PUBLICATION_FOR_DENOMINATOR_PAIR",)
                    if membership.decision.value == "INCLUDED"
                    else tuple(sorted(membership.reason_codes)),
                )
                for membership in freeze.memberships
                for preference in profile.enabled_preferences
            ),
        )

    def inspect_legacy_cohort(
        self,
        freeze_digest: str,
        profile_digest: str,
        policy_digest: str,
        *,
        exact_publication_digests: tuple[str, ...] = (),
        exact_attachment_digests: tuple[str, ...] = (),
    ) -> MatchweekEvaluation:
        """Inspect legacy per-match receipts under a separate cohort identity."""
        view = self.inspect_denominator(freeze_digest, profile_digest)
        try:
            return self._inspect_legacy_cohort(
                view, policy_digest, exact_publication_digests, exact_attachment_digests
            )
        except (ArtifactError, ValueError) as error:
            raise CB01EvaluationError(str(error), denominator=view) from error

    def _inspect_legacy_cohort(
        self,
        view: DenominatorView,
        policy_digest: str,
        exact_publication_digests: tuple[str, ...],
        exact_attachment_digests: tuple[str, ...],
    ) -> MatchweekEvaluation:
        cutoffs = MatchEvidenceCutoffRepository(self.store)
        if cutoffs.read_policy(policy_digest).rule == CORRECTED_RULE:
            raise CB01EvaluationError(
                "Corrected selection cannot join the legacy per-match cohort."
            )
        if len(set(exact_publication_digests)) != len(exact_publication_digests):
            raise CB01EvaluationError("Exact legacy receipt selection contains duplicates.")
        freeze = MatchweekMembershipRepository(self.store).get_by_digest(view.freeze_digest)
        assert freeze is not None
        denominator_pairs = {(row.membership_id, row.preference_id): row for row in view.rows}
        enrolled: dict[tuple[str, str], DenominatorRow] = {}
        cases: list[CaseView] = []
        for digest in sorted(exact_publication_digests):
            publication = self._body(digest, "FixtureEnrollmentPublication")
            batch = self._body(publication["batch_digest"], "FixtureEnrollmentBatch")
            anchor = batch["anchor"]
            boundary = cutoffs.replay(anchor["cutoff"]["id"])
            if (
                anchor["freeze"]["digest"] != view.freeze_digest.removeprefix("sha256:")
                or anchor["profile"]["digest"] != view.profile_digest
                or boundary.policy_digest != policy_digest
                or "causal_selection" in batch["lineage"]
            ):
                raise CB01EvaluationError("Receipt does not belong to the exact legacy cohort.")
            case = self.bootstrap.replay(digest)
            cases.append(case)
            for preference, enrollment_digest, record in case.records:
                pair = (anchor["membership"]["id"], preference)
                if pair not in denominator_pairs or pair in enrolled:
                    raise CB01EvaluationError("Legacy receipt repeats or adds a denominator pair.")
                enrolled[pair] = replace(
                    denominator_pairs[pair],
                    state=record["disposition"],
                    batch_digest=case.batch_digest,
                    publication_digest=case.publication_digest,
                    enrollment_digest=enrollment_digest,
                    reasons=tuple(record["reasons"]),
                )
        if len(set(exact_attachment_digests)) != len(exact_attachment_digests):
            raise CB01EvaluationError("Exact legacy outcome selection contains duplicates.")
        owner_by_record = {
            record_digest: case.publication_digest
            for case in cases
            for _, record_digest, _ in case.records
        }
        attachments: dict[str, list[str]] = {}
        for digest in sorted(exact_attachment_digests):
            kind, _ = decode_artifact(ArtifactStore(self.store).read_artifact(digest))
            if kind not in {"OutcomeAttachment", "OutcomeFactAttachment"}:
                raise CB01EvaluationError("Evaluation accepts only exact outcome attachments.")
            body = self._body(digest, kind)
            publication_digest = owner_by_record.get(body["enrollment_digest"])
            if publication_digest is None:
                raise CB01EvaluationError("Legacy outcome belongs to another cohort enrollment.")
            attachments.setdefault(publication_digest, []).append(digest)
        cases = [
            self.bootstrap.replay(
                case.publication_digest, tuple(attachments[case.publication_digest])
            )
            if case.publication_digest in attachments
            else case
            for case in cases
        ]
        rows = tuple(enrolled.get((row.membership_id, row.preference_id), row) for row in view.rows)
        return MatchweekEvaluation(
            policy_digest=policy_digest,
            common_cutoff_utc=None,
            selection=None,
            denominator=replace(view, rows=rows),
            cases=tuple(cases),
            cohort=LEGACY_COHORT,
            chronology_version=LEGACY_CHRONOLOGY,
            selection_contract="legacy-per-match-v1",
            qualification_status="HISTORICAL_INSPECTION_ONLY",
        )

    def _inspect_cohort(
        self,
        view: DenominatorView,
        policy_digest: str,
        selection_digest: str | None,
        exact_publication_digests: tuple[str, ...],
        exact_attachment_digests: tuple[str, ...],
        *,
        historical_inspection: bool = False,
    ) -> MatchweekEvaluation:
        freeze_digest, profile_digest = view.freeze_digest, view.profile_digest
        freeze = MatchweekMembershipRepository(self.store).get_by_digest(freeze_digest)
        assert freeze is not None  # Verified by independent denominator inspection.
        cutoffs = MatchEvidenceCutoffRepository(self.store)
        if cutoffs.read_policy(policy_digest).rule != CORRECTED_RULE:
            raise CB01EvaluationError("Legacy per-match policy cannot join the corrected cohort.")
        reasons = []
        common_cutoff: str | None = None
        try:
            boundaries = cutoffs.replay_for_freeze(freeze.freeze_id, policy_digest)
            if not boundaries or len({item.cutoff_at_utc for item in boundaries}) != 1:
                raise CB01EvaluationError("One exact common F07 boundary is required.")
            common_cutoff = boundaries[0].cutoff_at_utc
        except MatchEvidenceCutoffError:
            reasons.append("EXACT_F07_BOUNDARY_UNAVAILABLE")
        selection = None
        causal_cohort = False
        qualified: QualifiedCausalSelection | InspectedCausalSelection | None = None
        if selection_digest is None:
            reasons.append("MATCHWEEK_SELECTION_UNAVAILABLE")
        else:
            try:
                selection_manifest = MatchweekResearchRepository(
                    self.store
                )._artifacts.verify_manifest(selection_digest)
                f16_refs = tuple(
                    ref
                    for ref in selection_manifest.artifacts
                    if ref.media_type in {F16_MEDIA_TYPE, CAUSAL_MANIFEST_MEDIA_TYPE}
                )
                if len(f16_refs) != 1:
                    raise CB01EvaluationError("Selection must identify one exact F16 manifest.")
                if f16_refs[0].media_type == CAUSAL_MANIFEST_MEDIA_TYPE:
                    if historical_inspection:
                        from matchvet.causal_dispatch import inspect_causal_selection

                        qualified = inspect_causal_selection(self.store, selection_digest)
                    else:
                        qualified = resolve_qualified_causal_selection(self.store, selection_digest)
                    selection = qualified.selection
                    causal_cohort = True
                else:
                    if historical_inspection:
                        raise CB01EvaluationError(
                            "Historical inspection dispatch requires causal selection-v2."
                        )
                    selection = MatchweekResearchRepository(self.store).replay(selection_digest)
            except MatchweekResearchError as error:
                raise CB01EvaluationError(
                    "Exact selected evaluation lineage failed replay."
                ) from error
            manifest = json.loads(
                ArtifactStore(self.store).read_artifact(selection.f16_manifest_digest)
            )
            if (
                selection.freeze_id != freeze.freeze_id
                or selection.policy_digest != policy_digest
                or selection.cutoff_at_utc != common_cutoff
                or manifest["profile_digest"] != profile_digest
            ):
                raise CB01EvaluationError("Evaluation selection/freeze/Profile/policy/T differ.")
            if causal_cohort and (
                qualified is None or qualified.candidate.contract_version != CAUSAL_CONTRACT
            ):
                raise CB01EvaluationError("Unsupported causal selection candidate contract.")
        if exact_publication_digests and selection is None:
            raise CB01EvaluationError("Corrected receipts require the exact selected Matchweek.")
        if len(set(exact_publication_digests)) != len(exact_publication_digests):
            raise CB01EvaluationError("Exact receipt selection contains duplicates.")
        cases: list[CaseView] = []
        enrolled: dict[tuple[str, str], DenominatorRow] = {}
        denominator_pairs = {(row.membership_id, row.preference_id): row for row in view.rows}
        for digest in sorted(exact_publication_digests):
            publication = self._body(digest, "FixtureEnrollmentPublication")
            batch = self._body(publication["batch_digest"], "FixtureEnrollmentBatch")
            boundary = cutoffs.replay(batch["anchor"]["cutoff"]["id"])
            assert selection is not None
            if (
                batch["anchor"]["freeze"]["digest"] != freeze_digest.removeprefix("sha256:")
                or batch["anchor"]["profile"]["digest"] != profile_digest
                or boundary.policy_digest != policy_digest
                or normalize_utc(boundary.cutoff_at_utc) != normalize_utc(common_cutoff or "")
                or batch["lineage"]["f16_manifest"]["digest"] != selection.f16_manifest_digest
            ):
                raise CB01EvaluationError("Receipt selection/freeze/Profile/policy/T differ.")
            causal_origin = batch["lineage"].get("causal_selection")
            if causal_cohort:
                if qualified is None or causal_origin != qualified.lineage_value():
                    raise CB01EvaluationError("Receipt lacks the exact causal qualified origin.")
            elif causal_origin is not None:
                raise CB01EvaluationError(
                    "Causal CB01 receipt cannot join the historical v1 cohort."
                )
            case = self.bootstrap.replay(digest)
            cases.append(case)
            for preference, enrollment_digest, record in case.records:
                pair = (batch["anchor"]["membership"]["id"], preference)
                if pair not in denominator_pairs or pair in enrolled:
                    raise CB01EvaluationError("Receipt repeats or adds a denominator pair.")
                enrolled[pair] = replace(
                    denominator_pairs[pair],
                    state=record["disposition"],
                    batch_digest=case.batch_digest,
                    publication_digest=case.publication_digest,
                    enrollment_digest=enrollment_digest,
                    reasons=tuple(record["reasons"]),
                )
        if len(set(exact_attachment_digests)) != len(exact_attachment_digests):
            raise CB01EvaluationError("Exact outcome selection contains duplicates.")
        owner_by_record = {
            record_digest: case.publication_digest
            for case in cases
            for _, record_digest, _ in case.records
        }
        attachments_by_publication: dict[str, list[str]] = {}
        outcome_records: set[str] = set()
        for digest in sorted(exact_attachment_digests):
            kind, _ = decode_artifact(ArtifactStore(self.store).read_artifact(digest))
            if kind not in {"OutcomeAttachment", "OutcomeFactAttachment"}:
                raise CB01EvaluationError("Evaluation accepts only exact outcome attachments.")
            body = self._body(digest, kind)
            record_digest = body["enrollment_digest"]
            publication_digest = owner_by_record.get(record_digest)
            if publication_digest is None:
                raise CB01EvaluationError("Outcome belongs to another cohort enrollment.")
            if kind == "OutcomeAttachment":
                if record_digest in outcome_records:
                    raise CB01EvaluationError(
                        "Evaluation selects one outcome version per enrollment."
                    )
                outcome_records.add(record_digest)
            attachments_by_publication.setdefault(publication_digest, []).append(digest)
        cases = [
            self.bootstrap.replay(
                case.publication_digest,
                tuple(attachments_by_publication[case.publication_digest]),
            )
            if case.publication_digest in attachments_by_publication
            else case
            for case in cases
        ]
        failures: dict[str, list[str]] = {}
        unavailable_failures: set[str] = set()
        catalog_unavailable: set[str] = set()
        for metadata in self.store.artifact_catalog():
            if metadata.media_type != MEDIA_TYPES["TimestampFailure"]:
                continue
            try:
                failure = self._body(metadata.digest, "TimestampFailure")
                batch = self._body(failure["batch_digest"], "FixtureEnrollmentBatch")
            except ArtifactError, CB01EvaluationError, ValueError:
                catalog_unavailable.add(metadata.digest)
                continue
            anchor = batch["anchor"]
            if (
                anchor["freeze"]["digest"] != freeze_digest.removeprefix("sha256:")
                or anchor["profile"]["digest"] != profile_digest
            ):
                continue
            try:
                boundary = cutoffs.replay(anchor["cutoff"]["id"])
            except MatchEvidenceCutoffError:
                unavailable_failures.add(metadata.digest)
                continue
            else:
                if boundary.policy_digest != policy_digest:
                    continue
            if (
                selection is None
                or batch["lineage"]["f16_manifest"]["digest"] != selection.f16_manifest_digest
            ):
                unavailable_failures.add(metadata.digest)
                continue
            try:
                self.bootstrap.verify_failure_lineage(metadata.digest)
            except ArtifactError, ValueError:
                unavailable_failures.add(metadata.digest)
                continue
            failures.setdefault(anchor["membership"]["id"], []).append(metadata.digest)
        rows = tuple(
            replace(
                row,
                state="INCOMPLETE"
                if failures.get(row.membership_id)
                else "INCOMPLETE_FOR_NOT_ATTEMPTED",
                failure_digests=tuple(sorted(failures.get(row.membership_id, ()))),
                reasons=tuple(
                    sorted(
                        set(
                            (
                                *row.reasons,
                                *reasons,
                            )
                        )
                    )
                ),
            )
            if row.membership_state == "INCLUDED"
            else row
            for row in view.rows
        )
        rows = tuple(
            replace(
                enrolled[(row.membership_id, row.preference_id)],
                failure_digests=row.failure_digests,
            )
            if (row.membership_id, row.preference_id) in enrolled
            else row
            for row in rows
        )
        return MatchweekEvaluation(
            policy_digest=policy_digest,
            common_cutoff_utc=common_cutoff,
            selection=selection,
            denominator=replace(view, rows=rows),
            cases=tuple(cases),
            cohort=CAUSAL_COHORT if causal_cohort else COHORT,
            chronology_version=CHRONOLOGY_VERSION,
            selection_contract=(
                CAUSAL_CONTRACT if causal_cohort else HISTORICAL_SELECTION_CONTRACT
            ),
            qualification_status=(
                "HISTORICAL_INSPECTION_ONLY"
                if (historical_inspection and causal_cohort)
                or (selection is not None and not causal_cohort)
                else "PRESENTLY_QUALIFIED"
                if selection is not None
                else "NOT_QUALIFIED"
            ),
            unavailable_failure_digests=tuple(sorted(unavailable_failures)),
            catalog_unavailable_failure_digests=tuple(sorted(catalog_unavailable)),
        )

    def _body(self, digest: str, kind: str) -> dict[str, Any]:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            MEDIA_TYPES[kind],
            "PROTECTED",
        ):
            raise CB01EvaluationError("Missing or wrong protected CB01 cohort artifact.")
        return decode_artifact(ArtifactStore(self.store).read_artifact(digest), expected_kind=kind)[
            1
        ]

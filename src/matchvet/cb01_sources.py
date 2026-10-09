"""Exact, read-only joins from CB01 to F06, F07, F10, F11, F13, F14, and F16."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from matchvet.artifacts import ArtifactError, ArtifactStore, ManifestVersion
from matchvet.causal_dispatch import (
    InspectedCausalSelection,
    QualifiedCausalSelection,
    inspect_causal_selection,
    resolve_qualified_causal_selection,
)
from matchvet.cb01_schema import normalize_utc
from matchvet.f10 import V1_BASELINE_CATALOG, V2_REQUIREMENT_CATALOG
from matchvet.f13 import CAUSAL_RESULT_MEDIA_TYPE, RESULT_MEDIA_TYPE
from matchvet.f14 import (
    CAUSAL_DECISION_INPUT_MEDIA_TYPE,
    CAUSAL_DECISION_MEDIA_TYPE,
    DECISION_INPUT_MEDIA_TYPE,
    DECISION_MEDIA_TYPE,
    PreferenceProfile,
    PreferenceProfileRepository,
)
from matchvet.f16 import (
    CAUSAL_MANIFEST_MEDIA_TYPE,
    CAUSAL_MATCH_RESULT_MEDIA_TYPE,
    MATCH_RESULT_MEDIA_TYPE,
    F16MatchweekProcessor,
)
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import (
    MatchweekMembershipFreeze,
    MembershipDecision,
    MembershipState,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    CORRECTED_RULE,
    MatchweekResearchError,
    MatchweekResearchRepository,
)
from matchvet.store import Store


class CB01SourceError(ValueError):
    """An exact source reference or upstream replay failed CB01 preparation."""


@dataclass(frozen=True)
class FixtureEnrollmentInput:
    """Exact immutable references needed to prepare one F06 INCLUDED fixture."""

    freeze_id: str
    membership_id: str
    cutoff_id: str
    profile_digest: str
    f16_manifest_digest: str | None = None
    selection_digest: str | None = None


@dataclass(frozen=True)
class PreparedSources:
    """Exact replayed denominator, lineage, and pre-enrollment values."""

    request: FixtureEnrollmentInput
    freeze: MatchweekMembershipFreeze
    membership: MembershipDecision
    profile: PreferenceProfile
    anchor: dict[str, Any]
    lineage: dict[str, Any]
    pre_enrollments: tuple[dict[str, Any], ...]
    expected_preference_ids: tuple[str, ...]
    f16_manifest_digest: str | None
    f16_match_digest: str | None
    qualification_status: str


_FAMILY_IDS = ("CORNERS", "FIRST_HALF_GOALS", "FULL_TIME_GOALS", "SECOND_HALF_GOALS")
_UNAVAILABLE_REASON = "EXACT_UPSTREAM_LINEAGE_NOT_AVAILABLE"


def prepare_fixture_sources(
    store: Store,
    request: FixtureEnrollmentInput,
    *,
    historical_inspection: bool = False,
) -> PreparedSources:
    """Replay exact immutable inputs and preserve each enabled preference row."""
    freeze = MatchweekMembershipRepository(store).get_by_id(request.freeze_id)
    if freeze is None or freeze.freeze_id != request.freeze_id:
        raise CB01SourceError("Exact F06 freeze is missing or has a conflicting identity.")
    membership = next(
        (item for item in freeze.memberships if item.membership_id == request.membership_id), None
    )
    if membership is None:
        raise CB01SourceError("Exact F06 membership is not in the named freeze.")
    if membership.decision is not MembershipState.INCLUDED:
        raise CB01SourceError("CB01 fixture batches require an exact F06 INCLUDED membership.")
    if membership.controlling_revision.kickoff_precision != "INSTANT":
        raise CB01SourceError("An exact instant kickoff is required for CB01 chronology.")
    profile = PreferenceProfileRepository(store).replay(request.profile_digest)
    cutoff = MatchEvidenceCutoffRepository(store).replay(request.cutoff_id)
    if (
        cutoff.freeze_id,
        cutoff.freeze_digest,
        cutoff.membership_id,
        cutoff.membership_digest,
        cutoff.fixture_id,
        cutoff.fixture_revision_ref,
        cutoff.fixture_revision_digest,
    ) != (
        freeze.freeze_id,
        freeze.freeze_digest,
        membership.membership_id,
        membership.membership_digest,
        membership.fixture_id,
        membership.controlling_revision_id,
        membership.controlling_revision_digest,
    ):
        raise CB01SourceError("Exact F07 cutoff differs from the selected F06 membership.")

    policy = MatchEvidenceCutoffRepository(store).read_policy(cutoff.policy_digest)
    owner = MatchweekResearchRepository(store)
    causal_selection: QualifiedCausalSelection | InspectedCausalSelection | None = None
    selected = None
    if request.selection_digest is not None:
        if request.f16_manifest_digest is None:
            raise CB01SourceError("An exact selection requires its exact F16 manifest.")
        try:
            selection_manifest = owner._artifacts.verify_manifest(request.selection_digest)
            from matchvet.causal_selection import _version_v2

            if selection_manifest.versions == (
                ManifestVersion.from_identity(_version_v2("selection")),
            ):
                causal_selection = (
                    inspect_causal_selection(store, request.selection_digest)
                    if historical_inspection
                    else resolve_qualified_causal_selection(store, request.selection_digest)
                )
            else:
                selected = owner.replay(request.selection_digest)
        except (ArtifactError, MatchweekResearchError) as error:
            raise CB01SourceError("Exact CB01 selection lineage failed replay.") from error
    elif request.f16_manifest_digest is not None:
        metadata = store.artifact_metadata(request.f16_manifest_digest)
        if metadata is not None and metadata.media_type == CAUSAL_MANIFEST_MEDIA_TYPE:
            raise CB01SourceError(
                "Causal F16 requires an explicit exact qualified selection-v2 identity."
            )

    if request.f16_manifest_digest is not None and policy.rule == CORRECTED_RULE:
        if causal_selection is not None:
            if (
                causal_selection.selection_digest != request.selection_digest
                or causal_selection.f16_manifest_digest != request.f16_manifest_digest
                or causal_selection.selection.freeze_id != freeze.freeze_id
                or causal_selection.selection.policy_digest != cutoff.policy_digest
                or causal_selection.candidate.profile_digest != profile.digest
                or normalize_utc(causal_selection.selection.cutoff_at_utc)
                != normalize_utc(cutoff.cutoff_at_utc)
            ):
                raise CB01SourceError(
                    "Causal CB01 requires the exact qualified selected graph and common cutoff."
                )
        else:
            if selected is None:
                try:
                    selected = owner.selected_for_boundary(freeze.freeze_id, cutoff.policy_digest)
                except MatchweekResearchError as error:
                    raise CB01SourceError(
                        "Corrected CB01 selected Matchweek lineage failed replay."
                    ) from error
            if selected is None or (
                selected.f16_manifest_digest != request.f16_manifest_digest
                or normalize_utc(selected.cutoff_at_utc) != normalize_utc(cutoff.cutoff_at_utc)
            ):
                raise CB01SourceError(
                    "Corrected CB01 requires the exact selected F16/common cutoff."
                )

    home_id, away_id, kickoff = _fixture_identity(store, membership)
    scope = next((item for item in freeze.scopes if item.scope_id == membership.scope_id), None)
    if scope is None:
        raise CB01SourceError("F06 membership does not reference an exact frozen scope.")
    anchor = {
        "freeze": _reference(
            freeze.freeze_id, freeze.contract_version, _bare_digest(freeze.freeze_digest)
        ),
        "membership": _reference(
            membership.membership_id,
            str(freeze.payload_version),
            _bare_digest(membership.membership_digest),
        ),
        "fixture_revision": _reference(
            membership.controlling_revision_id,
            membership.controlling_revision.kickoff_precision,
            membership.controlling_revision_digest,
        ),
        "cutoff": _reference(request.cutoff_id, "f07-v1", _bare_digest(cutoff.digest)),
        "profile": _reference(request.profile_digest, profile.profile_version, profile.digest),
        "fixture_id": membership.fixture_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "competition_id": scope.league_key,
        "season_id": freeze.season,
        "matchweek_id": scope.scope_id,
        "kickoff_utc": normalize_utc(kickoff),
        "cutoff_utc": normalize_utc(cutoff.cutoff_at_utc),
    }

    f16_manifest_digest = request.f16_manifest_digest
    f16_match_digest: str | None = None
    lineage = _base_lineage(freeze, membership, cutoff, profile)
    model_value: dict[str, Any] | None = None
    decision_value: dict[str, Any] | None = None
    candidate_inputs: dict[str, Any] = {}
    candidate_input_bundle_digest: str | None = None
    if f16_manifest_digest is not None:
        manifest_metadata = store.artifact_metadata(f16_manifest_digest)
        is_causal = (
            manifest_metadata is not None
            and manifest_metadata.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        )
        if is_causal != (causal_selection is not None):
            raise CB01SourceError(
                "CB01 F16 contract and explicit selection-v2 dispatch do not match."
            )
        manifest = F16MatchweekProcessor(store).replay_manifest(f16_manifest_digest)
        manifest_value = manifest.to_dict()
        if (
            manifest.digest != f16_manifest_digest
            or manifest_value.get("freeze_id") != freeze.freeze_id
            or manifest_value.get("freeze_digest") != freeze.freeze_digest
            or manifest_value.get("profile_digest") != profile.digest
        ):
            raise CB01SourceError("Exact F16 manifest differs from F06 or Profile identity.")
        matches = [
            item
            for item in manifest.match_results
            if item.membership_id == membership.membership_id
        ]
        if len(matches) != 1:
            raise CB01SourceError("Exact F16 manifest does not name this membership exactly once.")
        matched = matches[0]
        if (matched.membership_digest, matched.cutoff_id, matched.cutoff_digest) != (
            membership.membership_digest,
            cutoff.cutoff_id,
            cutoff.digest,
        ):
            raise CB01SourceError("Exact F16 match lineage differs from F06/F07.")
        f16_match_digest = matched.match_result_digest
        artifacts = ArtifactStore(store)
        match_value = _read_json_artifact(
            store,
            artifacts,
            f16_match_digest,
            CAUSAL_MATCH_RESULT_MEDIA_TYPE if is_causal else MATCH_RESULT_MEDIA_TYPE,
        )
        if (
            match_value.get("freeze_id") != freeze.freeze_id
            or match_value.get("membership_id") != membership.membership_id
            or match_value.get("cutoff_id") != cutoff.cutoff_id
            or match_value.get("profile_digest") != profile.digest
        ):
            raise CB01SourceError("Exact F16 match result differs from its manifest or anchor.")
        f11_digest = cast(str, match_value["evidence_digest"])
        f13_digest = cast(str, match_value["model_digest"])
        f14_digest = cast(str, match_value["decision_digest"])
        model_value = _read_json_artifact(
            store,
            artifacts,
            f13_digest,
            CAUSAL_RESULT_MEDIA_TYPE if is_causal else RESULT_MEDIA_TYPE,
        )
        decision_value = _read_json_artifact(
            store,
            artifacts,
            f14_digest,
            CAUSAL_DECISION_MEDIA_TYPE if is_causal else DECISION_MEDIA_TYPE,
        )
        candidate_digest = causal_selection.candidate_contract_digest if causal_selection else None
        _validate_f13_identity(
            model_value, f13_digest, f11_digest, cutoff.cutoff_id, candidate_digest
        )
        _validate_f14_identity(
            decision_value,
            profile.digest,
            f11_digest,
            cutoff.cutoff_id,
            f13_digest,
            cast(str, match_value["policy_digest"]),
            candidate_digest,
        )
        lineage = _complete_lineage(
            freeze,
            membership,
            cutoff,
            profile,
            f16_manifest_digest,
            f16_match_digest,
            f11_digest,
            f13_digest,
            f14_digest,
            model_value,
            match_value,
            causal_selection,
        )
        if causal_selection is not None:
            lineage["causal_selection"] = causal_selection.lineage_value()
        decision_input_digest = cast(str, decision_value["input_bundle_digest"])
        candidate_input_bundle_digest = decision_input_digest
        decision_input = _read_json_artifact(
            store,
            artifacts,
            decision_input_digest,
            CAUSAL_DECISION_INPUT_MEDIA_TYPE if is_causal else DECISION_INPUT_MEDIA_TYPE,
        )
        if not isinstance(decision_input.get("candidate_inputs"), dict):
            raise CB01SourceError("Exact F14 candidate input bundle is malformed.")
        candidate_inputs = cast(dict[str, Any], decision_input["candidate_inputs"])
        if any(not isinstance(key, str) or not key for key in candidate_inputs):
            raise CB01SourceError("F14 CandidateInput preference IDs are malformed.")
        if set(candidate_inputs) - {p.preference_id for p in profile.enabled_preferences}:
            raise CB01SourceError("F14 input bundle contains a disabled preference.")

    preference_results: dict[str, dict[str, Any]] = {}
    if decision_value is not None:
        rows = decision_value.get("preference_results")
        if not isinstance(rows, list):
            raise CB01SourceError("Exact F14 decision preference denominator is malformed.")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("vetting"), dict):
                raise CB01SourceError("Exact F14 decision preference row is malformed.")
            preference = row["vetting"].get("preference")
            if not isinstance(preference, dict) or not isinstance(
                preference.get("preference_id"), str
            ):
                raise CB01SourceError("Exact F14 preference identity is malformed.")
            preference_results[preference["preference_id"]] = row

    expected = tuple(item.preference_id for item in profile.enabled_preferences)
    if preference_results and tuple(sorted(preference_results)) != expected:
        raise CB01SourceError("Exact F14 preference rows differ from the full Profile denominator.")

    pre_enrollments = tuple(
        _pre_enrollment(
            anchor,
            lineage,
            preference,
            model_value,
            decision_value,
            preference_results.get(preference.preference_id),
            candidate_inputs,
            candidate_input_bundle_digest,
            f11_digest=cast(str | None, lineage["f11_evidence"]["digest"]),
            f13_digest=cast(str | None, lineage["f13_result"]["digest"]),
            f14_digest=cast(str | None, lineage["f14_decision"]["digest"]),
        )
        for preference in profile.enabled_preferences
    )
    return PreparedSources(
        request=request,
        freeze=freeze,
        membership=membership,
        profile=profile,
        anchor=anchor,
        lineage=lineage,
        pre_enrollments=pre_enrollments,
        expected_preference_ids=expected,
        f16_manifest_digest=f16_manifest_digest,
        f16_match_digest=f16_match_digest,
        qualification_status=(
            "HISTORICAL_INSPECTION_ONLY"
            if isinstance(causal_selection, InspectedCausalSelection)
            else "PRESENTLY_QUALIFIED_CAUSAL_SELECTION_V2"
            if causal_selection is not None
            else "HISTORICAL_V1_SELECTION"
            if selected is not None
            else "NO_SELECTION_QUALIFICATION"
        ),
    )


def replay_fixture_sources(store: Store, batch_body: dict[str, Any]) -> PreparedSources:
    """Replay a retained batch's exact upstream identities before final publication."""
    anchor = batch_body["anchor"]
    lineage = batch_body["lineage"]
    f16 = lineage["f16_manifest"]
    request = FixtureEnrollmentInput(
        freeze_id=anchor["freeze"]["id"],
        membership_id=anchor["membership"]["id"],
        cutoff_id=anchor["cutoff"]["id"],
        profile_digest=anchor["profile"]["digest"],
        f16_manifest_digest=f16["digest"] if f16["state"] == "PRESENT" else None,
        selection_digest=(
            lineage["causal_selection"]["selection_digest"]
            if "causal_selection" in lineage
            else None
        ),
    )
    prepared = prepare_fixture_sources(store, request, historical_inspection=True)
    if prepared.anchor != anchor or prepared.lineage != lineage:
        raise CB01SourceError("Retained batch differs from exact replayed upstream lineage.")
    return prepared


def _base_lineage(
    freeze: MatchweekMembershipFreeze,
    membership: MembershipDecision,
    cutoff: Any,
    profile: PreferenceProfile,
) -> dict[str, Any]:
    return {
        "f06": _reference(
            freeze.freeze_id, freeze.contract_version, _bare_digest(freeze.freeze_digest)
        ),
        "f07": _reference(cutoff.cutoff_id, "f07-v1", _bare_digest(cutoff.digest)),
        "f10_catalog": _reference(
            V1_BASELINE_CATALOG[0], V1_BASELINE_CATALOG[1], V1_BASELINE_CATALOG[2]
        ),
        "f10_requirements": _reference(
            V2_REQUIREMENT_CATALOG.name,
            V2_REQUIREMENT_CATALOG.version,
            V2_REQUIREMENT_CATALOG.digest,
        ),
        "f11_evidence": _unavailable_reference(
            "UNPERFORMED", "F11_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f13_input": _unavailable_reference(
            "UNPERFORMED", "F13_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f13_result": _unavailable_reference(
            "UNPERFORMED", "F13_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f13_history": _unavailable_reference(
            "UNPERFORMED", "F13_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f14_profile": _reference(profile.digest, profile.profile_version, profile.digest),
        "f14_decision": _unavailable_reference(
            "UNPERFORMED", "F14_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f14_policy": _unavailable_reference(
            "UNPERFORMED", "F14_REFERENCE_REQUIRES_EXACT_F16_LINEAGE"
        ),
        "f16_manifest": _unavailable_reference("ABSENT", "F16_MANIFEST_NOT_SUPPLIED"),
        "f16_match_result": _unavailable_reference("ABSENT", "F16_MATCH_RESULT_NOT_SUPPLIED"),
    }


def _complete_lineage(
    freeze: MatchweekMembershipFreeze,
    membership: MembershipDecision,
    cutoff: Any,
    profile: PreferenceProfile,
    manifest_digest: str,
    match_digest: str,
    f11_digest: str,
    f13_digest: str,
    f14_digest: str,
    model: dict[str, Any],
    match_value: dict[str, Any],
    causal_selection: QualifiedCausalSelection | None = None,
) -> dict[str, Any]:
    lineage = _base_lineage(freeze, membership, cutoff, profile)
    model_inputs = model.get("inputs")
    if not isinstance(model_inputs, dict):
        raise CB01SourceError("F13 exact model input is malformed.")
    input_digest = model.get("input_digest")
    history_digest = model_inputs.get("history_snapshot_digest")
    policy_digest = match_value.get("policy_digest")
    if not isinstance(input_digest, str) or not isinstance(history_digest, str):
        raise CB01SourceError("F13 input or retained history digest is missing.")
    lineage.update(
        {
            "f11_evidence": _reference(f11_digest, "f11-evidence-v3", f11_digest),
            "f13_input": _reference(
                f"f13-input:{f13_digest}", "f13-v3" if causal_selection else "f13-v2", input_digest
            ),
            "f13_result": _reference(
                f13_digest, "f13-v3" if causal_selection else "f13-v2", f13_digest
            ),
            "f13_history": _reference(
                history_digest,
                "f13-history-v3" if causal_selection else "f13-history-v2",
                history_digest,
            ),
            "f14_decision": _reference(
                f14_digest, "f14-v3" if causal_selection else "f14-v2", f14_digest
            ),
            "f14_policy": _reference(
                f"f14-policy:{policy_digest}", "research-only", cast(str, policy_digest)
            ),
            "f16_manifest": _reference(
                manifest_digest, "f16-v2" if causal_selection else "f16-v1", manifest_digest
            ),
            "f16_match_result": _reference(
                match_digest, "f16-match-v2" if causal_selection else "f16-match-v1", match_digest
            ),
        }
    )
    return lineage


def _pre_enrollment(
    anchor: dict[str, Any],
    lineage: dict[str, Any],
    preference: Any,
    model: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    decision_row: dict[str, Any] | None,
    candidate_inputs: dict[str, Any],
    candidate_input_bundle_digest: str | None,
    *,
    f11_digest: str | None,
    f13_digest: str | None,
    f14_digest: str | None,
) -> dict[str, Any]:
    row = decision_row.get("vetting", {}) if decision_row else {}
    vetting_preference = row.get("preference", {}) if isinstance(row, dict) else {}
    if decision_row is not None and canonical_upstream_bytes(
        vetting_preference
    ) != canonical_upstream_bytes(preference.to_dict()):
        raise CB01SourceError("F14 preference contract differs from the exact T10 Profile.")
    family_key = _family_for(preference)
    f13_version = "v3" if "causal_selection" in lineage else "v2"
    family_result = model["results"].get(family_key) if model is not None else None
    forecast_families: list[dict[str, Any]] = []
    for family_id in _FAMILY_IDS:
        output = model["results"].get(family_id) if model is not None else None
        if not isinstance(output, dict):
            forecast_families.append(
                {
                    "family_id": family_id,
                    "input_reference": _unavailable_reference("UNPERFORMED", _UNAVAILABLE_REASON),
                    "fit_reference": _unavailable_reference("UNPERFORMED", _UNAVAILABLE_REASON),
                    "prediction_reference": _unavailable_reference(
                        "UNPERFORMED", _UNAVAILABLE_REASON
                    ),
                    "calibration_reference": _unavailable_reference(
                        "UNPERFORMED", _UNAVAILABLE_REASON
                    ),
                    "retained_family_payload": {},
                }
            )
            continue
        if model is None or not isinstance(model.get("input_digest"), str):
            raise CB01SourceError("Exact F13 model result is missing its input bundle identity.")
        forecast_families.append(
            {
                "family_id": family_id,
                "input_reference": _reference(
                    f"f13-input:{model['input_digest']}",
                    f"f13-{f13_version}",
                    model["input_digest"],
                ),
                "fit_reference": _artifact_reference(
                    output.get("model_artifact_digest"), f"f13-model-{f13_version}"
                ),
                "prediction_reference": _artifact_reference(
                    output.get("prediction_artifact_digest"), f"f13-distribution-{f13_version}"
                ),
                "calibration_reference": _artifact_reference(
                    output.get("calibration_artifact_digest"), f"f13-calibration-{f13_version}"
                ),
                "retained_family_payload": output,
            }
        )
    forecast = {
        "result_reference": (
            _artifact_reference(f13_digest, f"f13-{f13_version}")
            if f13_digest is not None
            else _unavailable_reference("UNPERFORMED", _UNAVAILABLE_REASON)
        ),
        "families": forecast_families,
    }
    support = _support(
        preference.preference_id,
        family_result,
        row if isinstance(row, dict) else {},
        candidate_inputs,
        candidate_input_bundle_digest,
        f13_version,
        f11_digest,
        f13_digest,
        f14_digest,
    )
    reasons: list[str] = []
    ready = (
        all(
            lineage[key]["state"] == "PRESENT"
            for key in (
                "f06",
                "f07",
                "f10_catalog",
                "f10_requirements",
                "f11_evidence",
                "f13_input",
                "f13_result",
                "f13_history",
                "f14_profile",
                "f14_decision",
                "f14_policy",
                "f16_manifest",
                "f16_match_result",
            )
        )
        and decision_row is not None
        and family_result is not None
    )
    if not ready:
        reasons.append("EXACT_F16_F11_F13_F14_LINEAGE_INCOMPLETE")
    eligibility = _eligibility(support)
    return {
        "anchor": anchor,
        "lineage": lineage,
        "preference": {
            "id": preference.preference_id,
            "catalog": preference.to_dict(),
            "family": preference.family.value,
            "side": preference.selection,
            "line": preference.to_dict()["line"],
            "phase": preference.phase.value,
            "settlement_topology": preference.settlement_rule,
        },
        "forecast": forecast,
        "support": support,
        "eligibility": eligibility,
        "disposition": "READY_FOR_WITNESS" if ready else "INCOMPLETE",
        "reasons": reasons,
        "software_identity": _software_reference(),
    }


def _support(
    preference_id: str,
    family_result: dict[str, Any] | None,
    row: dict[str, Any],
    candidate_inputs: dict[str, Any],
    candidate_input_bundle_digest: str | None,
    f13_version: str,
    f11_digest: str | None,
    f13_digest: str | None,
    f14_digest: str | None,
) -> dict[str, Any]:
    vetting = row.get("vetting", {}) if isinstance(row.get("vetting"), dict) else {}
    existing_candidate = candidate_inputs.get(preference_id)
    return {
        "candidate_input": (
            _reference(
                f"f14-candidate-input:{preference_id}",
                "f14-input-v3" if f13_version == "v3" else "f14-input-v2",
                candidate_input_bundle_digest,
            )
            if existing_candidate is not None and candidate_input_bundle_digest is not None
            else _unavailable_reference(
                "ABSENT" if f14_digest is not None else "UNPERFORMED",
                "NO_F14_CANDIDATE_INPUT_FOR_PREFERENCE"
                if f14_digest is not None
                else _UNAVAILABLE_REASON,
            )
        ),
        "research": (
            _reference(f11_digest, "f11-evidence-v3", f11_digest)
            if f11_digest is not None
            else _unavailable_reference("UNPERFORMED", _UNAVAILABLE_REASON)
        ),
        "adversarial_review": (
            _reference(
                f"f14-adversarial-review:{preference_id}",
                "f14-v3" if f13_version == "v3" else "f14-v2",
                f14_digest,
            )
            if vetting.get("adversarial_review") is not None and f14_digest is not None
            else _unavailable_reference(
                "ABSENT" if f14_digest is not None else "UNPERFORMED",
                "F14_ADVERSARIAL_REVIEW_ABSENT" if f14_digest is not None else _UNAVAILABLE_REASON,
            )
        ),
        "calibration": (
            _artifact_reference(
                family_result.get("calibration_artifact_digest"),
                f"f13-calibration-{f13_version}",
            )
            if isinstance(family_result, dict)
            else _unavailable_reference("UNPERFORMED", _UNAVAILABLE_REASON)
        ),
        "baseline": (
            _reference(
                f"f14-baseline:{preference_id}",
                "f14-v3" if f13_version == "v3" else "f14-v2",
                f14_digest,
            )
            if vetting.get("baseline") is not None and f14_digest is not None
            else _unavailable_reference(
                "ABSENT" if f14_digest is not None else "UNPERFORMED",
                "F14_BASELINE_ABSENT" if f14_digest is not None else _UNAVAILABLE_REASON,
            )
        ),
        "uncertainty_validation": _unavailable_reference(
            "UNPERFORMED", "NO_SEPARATE_UNCERTAINTY_VALIDATION_ARTIFACT"
        ),
        "independent_reference": _unavailable_reference(
            "UNPERFORMED", "NO_SEPARATE_INDEPENDENT_REFERENCE_ARTIFACT"
        ),
        "g6": _unavailable_reference("UNPERFORMED", "CB01_DOES_NOT_ASSESS_G6"),
        "g7": _unavailable_reference("UNPERFORMED", "CB01_DOES_NOT_ASSESS_G7"),
        "paired_strength": _unavailable_reference(
            "UNPERFORMED", "CB01_DOES_NOT_ASSESS_PAIRED_SELECTION_STRENGTH"
        ),
    }


def _eligibility(support: dict[str, Any]) -> dict[str, Any]:
    reasons = ["CB01 enrollment does not assess #70 eligibility."]
    dimensions = (
        "calibration",
        "data_quality",
        "reliability",
        "baseline",
        "adversarial_risk",
        "g6",
        "g7_reference",
        "paired_strength",
        "policy_validation",
    )
    source_keys = {
        "calibration": "calibration",
        "data_quality": "research",
        "reliability": "research",
        "baseline": "baseline",
        "adversarial_risk": "adversarial_review",
        "g6": "g6",
        "g7_reference": "g7",
        "paired_strength": "paired_strength",
        "policy_validation": "g6",
    }
    return {
        dimension: {
            "state": "NOT_ASSESSED",
            "reasons": reasons,
            "supporting_digests": (
                [support[source_keys[dimension]]["digest"]]
                if support[source_keys[dimension]]["state"] == "PRESENT"
                else []
            ),
        }
        for dimension in dimensions
    }


def _validate_f13_identity(
    value: dict[str, Any],
    result_digest: str,
    evidence_digest: str,
    cutoff_id: str,
    candidate_contract_digest: str | None = None,
) -> None:
    inputs = value.get("inputs")
    if (
        not isinstance(inputs, dict)
        or value.get("input_digest") != _sha256_json(inputs)
        or inputs.get("evidence_set_digest") != evidence_digest
        or inputs.get("cutoff_id") != cutoff_id
    ):
        raise CB01SourceError("Exact F13 result does not bind its retained F11/F07 inputs.")
    if not isinstance(value.get("results"), dict) or tuple(sorted(value["results"])) != _FAMILY_IDS:
        raise CB01SourceError("Exact F13 result does not retain all four model families.")
    expected_schema = 3 if candidate_contract_digest is not None else 2
    if value.get("schema_version") != expected_schema or (
        candidate_contract_digest is not None
        and value.get("candidate_contract_digest") != candidate_contract_digest
    ):
        raise CB01SourceError("Unsupported F13 model result schema or candidate for CB01.")
    if not result_digest:
        raise CB01SourceError("F13 result digest is missing.")


def _validate_f14_identity(
    value: dict[str, Any],
    profile_digest: str,
    evidence_digest: str,
    cutoff_id: str,
    f13_digest: str,
    policy_digest: str,
    candidate_contract_digest: str | None = None,
) -> None:
    lineage = value.get("lineage")
    if not isinstance(lineage, dict) or (
        lineage.get("profile_digest"),
        lineage.get("evidence_digest"),
        lineage.get("cutoff_id"),
        lineage.get("f13_model_result_digest"),
        lineage.get("t15_policy_digest"),
    ) != (profile_digest, evidence_digest, cutoff_id, f13_digest, policy_digest):
        raise CB01SourceError("Exact F14 decision does not bind its F06/F07/F11/F13/F16 lineage.")
    if candidate_contract_digest is not None and (
        value.get("candidate_contract_digest") != candidate_contract_digest
        or lineage.get("candidate_contract_digest") != candidate_contract_digest
    ):
        raise CB01SourceError("Exact F14 decision differs from the qualified causal candidate.")


def _fixture_identity(store: Store, membership: MembershipDecision) -> tuple[str, str, str]:
    row = (
        store._connection_for_repository()
        .execute(
            """SELECT f.home_team_id, f.away_team_id, r.kickoff_utc, r.revision_digest
               FROM fixture_revisions r JOIN fixtures f ON f.fixture_id = r.fixture_id
               WHERE r.revision_id = ? AND r.fixture_id = ?""",
            (membership.controlling_revision_id, membership.fixture_id),
        )
        .fetchone()
    )
    if row is None or str(row[3]) != membership.controlling_revision_digest:
        raise CB01SourceError("Exact F06 controlling fixture revision cannot be replayed.")
    if membership.controlling_revision.kickoff_precision != "INSTANT":
        raise CB01SourceError("An exact instant kickoff is required for CB01 chronology.")
    return str(row[0]), str(row[1]), str(row[2])


def _read_json_artifact(
    store: Store, artifacts: ArtifactStore, digest: str, media_type: str
) -> dict[str, Any]:
    metadata = store.artifact_metadata(digest)
    if metadata is None or (metadata.media_type, metadata.retention_class) != (
        media_type,
        "PROTECTED",
    ):
        raise CB01SourceError(f"Missing or wrong protected upstream artifact {media_type}.")
    try:
        content = artifacts.read_artifact(digest)
        value = json.loads(content)
    except (ValueError, TypeError) as error:
        raise CB01SourceError("Protected upstream artifact is malformed JSON.") from error
    if not isinstance(value, dict) or canonical_upstream_bytes(value) != content:
        raise CB01SourceError("Protected upstream artifact is noncanonical.")
    return cast(dict[str, Any], value)


def canonical_upstream_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode()


def _sha256_json(value: object) -> str:
    import hashlib

    return hashlib.sha256(canonical_upstream_bytes(value)).hexdigest()


def _reference(identifier: str, version: str, digest: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "version": version,
        "digest": _bare_digest(digest),
        "state": "PRESENT",
        "reasons": [],
    }


def _artifact_reference(digest: object, version: str) -> dict[str, Any]:
    if not isinstance(digest, str):
        return _unavailable_reference("UNPERFORMED", "EXACT_ARTIFACT_REFERENCE_NOT_AVAILABLE")
    return _reference(digest, version, digest)


def _unavailable_reference(state: str, reason: str) -> dict[str, Any]:
    return {"id": None, "version": None, "digest": None, "state": state, "reasons": [reason]}


def _software_reference() -> dict[str, Any]:
    from hashlib import sha256
    from pathlib import Path

    import matchvet.cb01 as implementation

    digest = sha256(Path(implementation.__file__).read_bytes()).hexdigest()
    return _reference("matchvet.cb01", "0.1.0", digest)


def _bare_digest(value: str) -> str:
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise CB01SourceError("Upstream artifact digest has an unsupported namespace or spelling.")
    return digest


def _family_for(preference: Any) -> str:
    family = preference.family.value
    if family == "First-Half Over":
        return "FIRST_HALF_GOALS"
    if family == "Second-Half Over":
        return "SECOND_HALF_GOALS"
    if family in {
        "Corner Match Winner",
        "Full-Match Total Corners Over",
        "Home Team Corners Over",
        "Away Team Corners Over",
    }:
        return "CORNERS"
    return "FULL_TIME_GOALS"

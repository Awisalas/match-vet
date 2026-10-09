"""Bounded, immutable corrected-chronology capture for diagnostic RESEARCH_ONLY cases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.candidate_support import SupportState
from matchvet.causal_candidate import resolve as resolve_causal_candidate
from matchvet.causal_dispatch import resolve_qualified_causal_selection
from matchvet.causal_selection import _PROVENANCE
from matchvet.cb01 import BatchResult, BootstrapRepository, CB01Error
from matchvet.cb01_schema import MEDIA_TYPES as CB01_MEDIA_TYPES
from matchvet.cb01_schema import decode_artifact
from matchvet.cb01_sources import (
    CB01SourceError,
    FixtureEnrollmentInput,
    replay_fixture_sources,
)
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import F16MatchResult
from matchvet.f19 import F19Error, SettlementRepository
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.matchweek_membership_repository import (
    MatchweekMembershipIntegrityError,
    MatchweekMembershipRepository,
)
from matchvet.matchweek_research import MatchweekResearchError, MatchweekResearchRepository
from matchvet.store import Store
from matchvet.t15 import PolicyStatus, PolicyVersion

CAPTURE_INDEX_MEDIA_TYPE = "application/vnd.matchvet.research-capture-index.v1+json"
CAPTURE_SCHEMA_VERSION = 1
SOURCE_USE_DECISION_CONTRACT = "research-real-source-use-decision-v1"


class CaptureError(ValueError):
    """An exact bootstrap capture, authorization, or replay check failed."""


class CaptureState(StrEnum):
    MISSING = "MISSING"
    UNATTEMPTED = "UNATTEMPTED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"
    UNSUPPORTED = "UNSUPPORTED"
    INCOMPLETE = "INCOMPLETE"
    ENROLLED = "ENROLLED"
    EXCLUDED = "EXCLUDED"


class SourceUseState(StrEnum):
    APPROVED = "APPROVED"
    WITHDRAWN = "WITHDRAWN"


_CB01_CAPTURE_STATES: Mapping[str, CaptureState] = {
    "ENROLLED_LIVE": CaptureState.ENROLLED,
    "INCOMPLETE": CaptureState.INCOMPLETE,
    "EXCLUDED": CaptureState.EXCLUDED,
}


@dataclass(frozen=True)
class SourceUseDecision:
    """Decision returned by the separately controlled real-source authorization."""

    state: SourceUseState | str
    decision_digest: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", SourceUseState(self.state))
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if not self.decision_digest:
            raise ValueError("A source-use decision needs its exact protected artifact digest.")
        if self.state is SourceUseState.APPROVED and self.reason_codes:
            raise ValueError("An approved source-use decision cannot contain refusal reasons.")
        if self.state is SourceUseState.WITHDRAWN and not self.reason_codes:
            raise ValueError("A withdrawn source-use decision needs exact reason codes.")


class SourceUseAuthorizer(Protocol):
    """Trusted runtime boundary for exact, operational real-source authorization."""

    def authorize_real_source_use(
        self,
        *,
        freeze_digest: str,
        selection_digest: str,
        profile_digest: str,
        scope_ids: tuple[str, ...],
    ) -> SourceUseDecision:
        """Return a retained approval/withdrawal decision for this exact capture."""


@dataclass(frozen=True)
class CaptureIndex:
    canonical_bytes: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical_bytes))


class ResearchCaptureRepository:
    """Create/replay one exact seven-scope index and gate any CB01 collection."""

    def __init__(
        self,
        store: Store,
        *,
        source_authorizer: SourceUseAuthorizer | None = None,
        bootstrap: BootstrapRepository | None = None,
    ) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)
        self.source_authorizer = source_authorizer
        self.bootstrap = bootstrap or BootstrapRepository(store)

    def capture_week(
        self,
        selection_digest: str,
        *,
        prior_index_digest: str | None = None,
        enroll: bool = False,
    ) -> CaptureIndex:
        """Build an offline index or append one gated, bounded CB01 enrollment pass.

        An enrollment continuation must name the exact index it extends. One call
        enrolls at most one CB01 batch per INCLUDED membership in that seven-scope
        freeze; CB01 itself permits only its normal single attempt here.
        """
        if prior_index_digest is None:
            if enroll:
                raise CaptureError("CB01 enrollment requires an exact prior capture-index digest.")
            value = self._base_value(selection_digest)
            return self._publish(value)
        if not enroll:
            raise CaptureError("A continuation requires explicit CB01 enrollment mode.")

        prior = self.replay(prior_index_digest)
        prior_value = prior.to_dict()
        if prior_value["selection"]["digest"] != selection_digest:
            raise CaptureError("Capture continuation must name the prior exact selection.")
        decision = self._source_use_decision(prior_value)
        if decision.state is SourceUseState.WITHDRAWN:
            value = self._successor_value(prior_value, prior_index_digest)
            value["source_use"] = self._source_use_value(decision)
            value["capture_state"] = CaptureState.WITHDRAWN.value
            for row in value["denominator_rows"]:
                if row["membership_state"] == "INCLUDED" and row["cb01"] == _empty_cb01():
                    row["capture_state"] = CaptureState.WITHDRAWN.value
                    row["capture_reasons"] = list(decision.reason_codes)
            return self._publish(value)

        try:
            qualified = resolve_qualified_causal_selection(self.store, selection_digest)
        except MatchweekResearchError as error:
            raise CaptureError(
                "The exact causal-witness profile is not currently authorized."
            ) from error
        if (
            qualified.f16_manifest_digest != prior_value["graph"]["f16_manifest_digest"]
            or qualified.candidate_contract_digest != prior_value["graph"]["candidate_digest"]
            or qualified.candidate.witness_profile_digest
            != prior_value["chronology"]["witness_profile_digest"]
        ):
            raise CaptureError(
                "Current causal authorization differs from the exact selected graph."
            )

        value = self._successor_value(prior_value, prior_index_digest)
        value["source_use"] = self._source_use_value(decision)
        for membership_id in sorted(
            {
                row["membership_id"]
                for row in value["denominator_rows"]
                if row["membership_state"] == "INCLUDED"
            }
        ):
            member_rows = [
                row for row in value["denominator_rows"] if row["membership_id"] == membership_id
            ]
            if all(row["cb01"]["batch_digest"] is not None for row in member_rows):
                continue
            first = member_rows[0]
            result = self.bootstrap.enroll_fixture(
                FixtureEnrollmentInput(
                    freeze_id=value["freeze"]["freeze_id"],
                    membership_id=membership_id,
                    cutoff_id=first["lineage"]["f07_cutoff_id"],
                    profile_digest=value["profile"]["digest"],
                    f16_manifest_digest=value["graph"]["f16_manifest_digest"],
                    selection_digest=selection_digest,
                )
            )
            self._apply_batch_result(value, member_rows, result)
        row_states = {row["capture_state"] for row in value["denominator_rows"]}
        value["capture_state"] = (
            CaptureState.FAILED.value
            if CaptureState.FAILED.value in row_states
            else CaptureState.ENROLLED.value
            if row_states == {CaptureState.ENROLLED.value}
            else CaptureState.INCOMPLETE.value
        )
        return self._publish(value)

    def attach_outcome(
        self,
        index_digest: str,
        *,
        membership_id: str,
        preference_id: str,
        settlement_digest: str,
        exact_fact_evidence: tuple[str, ...] | None = None,
        predecessor_attachment_digest: str | None = None,
    ) -> CaptureIndex:
        """Append one exact F19 version to its exact CB01 enrollment and index."""
        if settlement_digest == "latest":
            raise CaptureError("F19 attachment requires an exact settlement digest, never latest.")
        current = self.replay(index_digest)
        value = current.to_dict()
        row = self._denominator_row(value, membership_id, preference_id)
        if row["capture_state"] != CaptureState.ENROLLED.value:
            raise CaptureError("An F19 outcome requires this exact row's live CB01 enrollment.")
        enrollment_digest = row["cb01"]["enrollment_digest"]
        if not isinstance(enrollment_digest, str):
            raise CaptureError("The selected denominator row has no exact enrollment record.")
        if exact_fact_evidence is not None and len(exact_fact_evidence) != len(
            set(exact_fact_evidence)
        ):
            raise CaptureError("Exact F19 fact-evidence selection contains duplicate digests.")

        settlement = SettlementRepository(self.store).replay(settlement_digest).to_dict()
        expected_identity = {
            "selection_digest": value["selection"]["digest"],
            "manifest_digest": value["graph"]["f16_manifest_digest"],
            "match_result_digest": row["lineage"]["f16_match_result_digest"],
            "preference_id": preference_id,
        }
        if any(settlement.get(key) != expected for key, expected in expected_identity.items()):
            raise CaptureError("F19 record differs from this exact selected enrollment lineage.")
        _require_source_backed_post_kickoff(
            settlement,
            _time(
                self._membership_kickoff(value, membership_id),
                "F06 controlling kickoff",
            ),
        )

        history = row["outcome_history"]
        if not isinstance(history, list):
            raise CaptureError("Capture index outcome history is malformed.")
        if predecessor_attachment_digest is None:
            if history or settlement["correction_sequence"] != 0:
                raise CaptureError("An F19 correction requires its exact attachment predecessor.")
        elif (
            not history or history[-1]["outcome_attachment_digest"] != predecessor_attachment_digest
        ):
            raise CaptureError("Outcome correction requires the exact last attached predecessor.")

        try:
            outcome_digest, fact_digest = self.bootstrap.attach_outcome(
                enrollment_digest,
                settlement_digest,
                exact_fact_evidence,
                predecessor_attachment_digest,
            )
        except (CB01Error, F19Error) as error:
            raise CaptureError("Exact CB01/F19 outcome attachment failed replay.") from error
        row["outcome_history"].append(
            {
                "correction_sequence": settlement["correction_sequence"],
                "fact_attachment_digest": fact_digest,
                "outcome_attachment_digest": outcome_digest,
                "predecessor_attachment_digest": predecessor_attachment_digest,
                "settlement_digest": settlement_digest,
                "source_provenance": _source_provenance(settlement),
            }
        )
        row["outcome_state"] = "PRESENT"
        value["capture_state"] = "OUTCOMES_ATTACHED"
        return self._publish(self._successor_value(value, index_digest))

    def replay(self, index_digest: str) -> CaptureIndex:
        """Replay one explicitly named protected index and all exact listed lineage."""
        return self._replay(index_digest, set())

    def _replay(self, index_digest: str, seen: set[str]) -> CaptureIndex:
        if index_digest in seen:
            raise CaptureError("Capture-index predecessor chain contains a cycle.")
        seen.add(index_digest)
        metadata = self.store.artifact_metadata(index_digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            CAPTURE_INDEX_MEDIA_TYPE,
            "PROTECTED",
        ):
            raise CaptureError("Exact protected capture index is unavailable.")
        content = self.artifacts.read_artifact(index_digest)
        try:
            value = json.loads(content)
        except (TypeError, ValueError) as error:
            raise CaptureError("Capture index is malformed JSON.") from error
        if (
            not isinstance(value, dict)
            or canonical_json(value).encode("utf-8") != content
            or _digest(content) != index_digest
            or value.get("schema_version") != CAPTURE_SCHEMA_VERSION
            or value.get("contract") != "research-capture-index-v1"
        ):
            raise CaptureError("Capture index is noncanonical or has an unsupported identity.")

        expected = self._base_value(value["selection"]["digest"])
        _same_base_identity(value, expected)
        predecessor = value.get("predecessor_digest")
        if predecessor is not None:
            if not isinstance(predecessor, str):
                raise CaptureError("Capture index predecessor identity is malformed.")
            prior = self._replay(predecessor, seen).to_dict()
            for key in ("freeze", "profile", "selection", "graph", "chronology", "policy"):
                if value[key] != prior[key]:
                    raise CaptureError(
                        "Capture index successor changed its selected graph identity."
                    )
            if len(value["denominator_rows"]) != len(prior["denominator_rows"]):
                raise CaptureError("Capture index successor changed its full denominator size.")

        self._verify_rows(value)
        if value.get("source_use") is not None:
            source_use = value["source_use"]
            if not isinstance(source_use, dict) or source_use.get("state") not in {
                item.value for item in SourceUseState
            }:
                raise CaptureError("Capture index source-use decision is malformed.")
            decision_digest = source_use.get("decision_digest")
            if not isinstance(decision_digest, str):
                raise CaptureError("Capture index source-use artifact identity is malformed.")
            decision = _read_protected_json(self.store, decision_digest)
            expected_decision = _source_use_binding(
                value,
                state=source_use["state"],
                reason_codes=source_use.get("reason_codes"),
            )
            if decision != expected_decision:
                raise CaptureError("Exact source-use decision does not bind this capture index.")
        return CaptureIndex(content)

    def _base_value(self, selection_digest: str) -> dict[str, Any]:
        try:
            selected = MatchweekResearchRepository(self.store).inspect_causal(selection_digest)
            manifest_value = _read_protected_json(self.store, selected.f16_manifest_digest)
            candidate_digest = manifest_value.get("candidate_contract_digest")
            if not isinstance(candidate_digest, str):
                raise CaptureError("Selected F16 lacks its exact causal candidate identity.")
            candidate = resolve_causal_candidate(self.store, candidate_digest)
            if (
                candidate.digest != candidate_digest
                or candidate.freeze_id != selected.freeze_id
                or candidate.cutoff_policy_digest != selected.policy_digest
                or candidate.cutoff_at_utc != selected.cutoff_at_utc
                or candidate.profile_digest != manifest_value.get("profile_digest")
                or candidate.decision_policy_digest != manifest_value.get("policy_digest")
            ):
                raise CaptureError("Exact F16 and #80 candidate identities differ.")
            freeze = MatchweekMembershipRepository(self.store).get_by_id(selected.freeze_id)
            if freeze is None:
                raise CaptureError("Selected graph F06 freeze is missing.")
            if len(freeze.scopes) != 7:
                raise CaptureError("Capture requires the exact seven-scope F06 freeze.")
            profile = PreferenceProfileRepository(self.store).replay(candidate.profile_digest)
            preferences = tuple(item.preference_id for item in profile.enabled_preferences)
            if not preferences or preferences != tuple(sorted(set(preferences))):
                raise CaptureError("Exact enabled-preference denominator is empty or malformed.")
            cutoffs = MatchEvidenceCutoffRepository(self.store).replay_for_freeze(
                freeze.freeze_id, selected.policy_digest
            )
            if not cutoffs or len({item.cutoff_at_utc for item in cutoffs}) != 1:
                raise CaptureError("Selected F07 rows do not have one exact common T.")
            common_t = cutoffs[0].cutoff_at_utc
            if common_t != selected.cutoff_at_utc:
                raise CaptureError("Selected F16 and exact F07 rows disagree on common T.")
            if tuple(scope.scope_id for scope in freeze.scopes) != tuple(
                scope.scope_id for scope in _expected_scopes(freeze.matchweek_friday, freeze.season)
            ):
                raise CaptureError("F06 freeze is not the exact canonical seven-scope Friday week.")

            policy = PolicyVersion.from_mapping(manifest_value["policy"])
            _require_diagnostic_policy(policy)
            if (
                manifest_value.get("status") != "RESEARCH_ONLY"
                or manifest_value.get("freeze_digest") != freeze.freeze_digest
                or manifest_value.get("profile_digest") != profile.digest
                or manifest_value.get("candidate_contract_digest") != candidate.digest
            ):
                raise CaptureError("F16 manifest differs from the exact F06/Profile selection.")
            cutoffs_by_membership = {item.membership_id: item for item in cutoffs}
            raw_matches = manifest_value.get("matches")
            if not isinstance(raw_matches, list):
                raise CaptureError("Exact F16 manifest match rows are malformed.")
            match_results = tuple(
                F16MatchResult(**cast(dict[str, str], row))
                for row in raw_matches
                if isinstance(row, Mapping)
            )
            if len(match_results) != len(raw_matches):
                raise CaptureError("Exact F16 manifest contains malformed match rows.")
            matches = {item.membership_id: item for item in match_results}
            included_ids = {
                item.membership_id
                for item in freeze.memberships
                if item.decision.value == "INCLUDED"
            }
            if set(cutoffs_by_membership) != included_ids or set(matches) != included_ids:
                raise CaptureError("Selected graph is not complete for every INCLUDED membership.")

            receipt = self.artifacts.verify_manifest(selected.completion_receipt_digest)
            provenance_refs = [ref for ref in receipt.artifacts if ref.media_type == _PROVENANCE]
            if len(provenance_refs) != 1:
                raise CaptureError("Exact #80 completion receipt has no unique event witness.")
            provenance_digest = provenance_refs[0].digest
            provenance_raw = self.artifacts.read_artifact(provenance_digest)
            provenance = json.loads(provenance_raw)
            if (
                not isinstance(provenance, dict)
                or canonical_json(provenance).encode("utf-8") != provenance_raw
                or provenance.get("profile_digest") != candidate.witness_profile_digest
            ):
                raise CaptureError("#80 event witness provenance differs from its exact profile.")
            lower = _time(provenance.get("lower_bound_utc"), "#80 witness lower bound")
            upper = _time(provenance.get("upper_bound_utc"), "#80 witness upper bound")
            if lower > upper:
                raise CaptureError("The signed #80 witness interval is reversed.")
            require_pre_t_witness(upper, _time(common_t, "common T"))
            evidence = provenance.get("evidence")
            if not isinstance(evidence, dict):
                raise CaptureError("#80 event witness provenance lacks exact evidence references.")
            binding_digest = evidence.get("binding")
            response_digest = evidence.get("response")
            if not isinstance(binding_digest, str) or not isinstance(response_digest, str):
                raise CaptureError("#80 event witness lacks its exact binding or signed response.")
            binding = _read_protected_json(self.store, binding_digest)
            if (
                binding.get("selection_digest") != selection_digest
                or binding.get("f16_digest") != selected.f16_manifest_digest
            ):
                raise CaptureError("#80 signed binding differs from the complete exact F16 graph.")

            included_members = tuple(
                member for member in freeze.memberships if member.decision.value == "INCLUDED"
            )
            excluded_memberships = [
                {
                    "membership_digest": member.membership_digest,
                    "membership_id": member.membership_id,
                    "reason_code": member.reason_code,
                    "reason_codes": list(member.reason_codes),
                    "scope_id": member.scope_id,
                }
                for member in freeze.memberships
                if member.decision.value != "INCLUDED"
            ]
            rows: list[dict[str, Any]] = []
            for member in included_members:
                scope = next(item for item in freeze.scopes if item.scope_id == member.scope_id)
                for preference in profile.enabled_preferences:
                    base: dict[str, Any] = {
                        "capture_reasons": ["CB01_NOT_ATTEMPTED"],
                        "capture_state": CaptureState.UNATTEMPTED.value,
                        "cb01": _empty_cb01(),
                        "candidate_input": {
                            "reason_codes": [
                                "F14_CANDIDATE_INPUT_SUPPORT_NOT_VERSIONED_IN_SELECTED_F16"
                            ],
                            "state": SupportState.UNKNOWN.value,
                        },
                        "f06": {
                            "decision": member.decision.value,
                            "membership_digest": member.membership_digest,
                            "membership_id": member.membership_id,
                            "reason_code": member.reason_code,
                            "reason_codes": list(member.reason_codes),
                            "scope_id": scope.scope_id,
                        },
                        "f14": None,
                        "f13": {"families": [], "result_digest": None},
                        "lineage": {
                            "f06_membership_digest": member.membership_digest,
                            "f06_membership_id": member.membership_id,
                            "f07_cutoff_digest": None,
                            "f07_cutoff_id": None,
                            "f11_evidence_digest": None,
                            "f13_result_digest": None,
                            "f14_decision_digest": None,
                            "f16_manifest_digest": selected.f16_manifest_digest,
                            "f16_match_result_digest": None,
                        },
                        "membership_id": member.membership_id,
                        "membership_state": member.decision.value,
                        "outcome_history": [],
                        "outcome_state": "MISSING",
                        "preference_id": preference.preference_id,
                        "scope_id": scope.scope_id,
                    }
                    cutoff = cutoffs_by_membership[member.membership_id]
                    match = matches[member.membership_id]
                    if member.decision.value == "INCLUDED":
                        decision = _read_protected_json(self.store, match.decision_digest)
                        model = _read_protected_json(self.store, match.model_digest)
                        preference_rows = [
                            row
                            for row in decision["preference_results"]
                            if row["vetting"]["preference"]["preference_id"]
                            == preference.preference_id
                        ]
                        if len(preference_rows) != 1:
                            raise CaptureError("F14 does not retain exactly one preference row.")
                        model_families = model.get("results")
                        if not isinstance(model_families, Mapping):
                            raise CaptureError("F13 exact result has no raw family outputs.")
                        family_rows = []
                        for family_id, output in sorted(model_families.items()):
                            if not isinstance(output, Mapping):
                                raise CaptureError("F13 raw family output is malformed.")
                            calibration = output.get("calibration")
                            family_rows.append(
                                {
                                    "calibration_artifact_digest": output.get(
                                        "calibration_artifact_digest"
                                    ),
                                    "calibration_availability_state": (
                                        calibration.get("status", "UNKNOWN")
                                        if isinstance(calibration, Mapping)
                                        else "UNKNOWN"
                                    ),
                                    "calibrated_prediction_is_validation": False,
                                    "family_id": family_id,
                                    "raw_prediction_artifact_digest": output.get(
                                        "prediction_artifact_digest"
                                    ),
                                    "raw_prediction_state": (
                                        "PRESENT"
                                        if isinstance(output.get("prediction_artifact_digest"), str)
                                        else "MISSING"
                                    ),
                                }
                            )
                        input_digest = decision["input_bundle_digest"]
                        decision_input = _read_protected_json(self.store, input_digest)
                        supplied_candidate = decision_input.get("candidate_inputs", {}).get(
                            preference.preference_id
                        )
                        candidate_status = dict(base["candidate_input"])
                        if supplied_candidate is None:
                            candidate_status["reason_codes"].append(
                                "NO_F14_CANDIDATE_INPUT_FOR_PREFERENCE"
                            )
                        else:
                            candidate_status["untrusted_value_digest"] = _digest(
                                canonical_json(supplied_candidate).encode("utf-8")
                            )
                            candidate_status["reason_codes"].append(
                                "CANDIDATE_INPUT_LACKS_VERSIONED_SUPPORT_PROOF"
                            )
                        base["candidate_input"] = candidate_status
                        base["f13"] = {
                            "families": family_rows,
                            "result_digest": match.model_digest,
                        }
                        base["f14"] = {
                            "decision_digest": match.decision_digest,
                            "input_bundle_digest": input_digest,
                            "preference_result": preference_rows[0],
                        }
                        base["lineage"] = {
                            "f06_membership_digest": member.membership_digest,
                            "f06_membership_id": member.membership_id,
                            "f07_cutoff_digest": cutoff.digest,
                            "f07_cutoff_id": cutoff.cutoff_id,
                            "f11_evidence_digest": match.evidence_digest,
                            "f13_result_digest": match.model_digest,
                            "f14_decision_digest": match.decision_digest,
                            "f16_manifest_digest": selected.f16_manifest_digest,
                            "f16_match_result_digest": match.match_result_digest,
                        }
                    rows.append(base)

            policy_value = cast(dict[str, Any], json.loads(canonical_json(policy.to_dict())))
            return {
                "capture_state": "INDEXED",
                "chronology": {
                    "common_T_utc": common_t,
                    "selection_witness": {
                        "completion_receipt_digest": selected.completion_receipt_digest,
                        "lower_bound_utc": provenance["lower_bound_utc"],
                        "provenance_digest": provenance_digest,
                        "signed_binding_digest": binding_digest,
                        "signed_response_digest": response_digest,
                        "upper_bound_utc": provenance["upper_bound_utc"],
                    },
                    "witness_profile_digest": candidate.witness_profile_digest,
                },
                "contract": "research-capture-index-v1",
                "denominator": {
                    "included_membership_count": len(included_ids),
                    "membership_count": len(included_ids),
                    "preference_count": len(preferences),
                    "row_count": len(included_ids) * len(preferences),
                },
                "denominator_rows": rows,
                "excluded_memberships": excluded_memberships,
                "freeze": {
                    "assessment_digest": freeze.assessment_digest,
                    "digest": freeze.freeze_digest,
                    "friday": freeze.matchweek_friday,
                    "freeze_id": freeze.freeze_id,
                    "membership_count": len(freeze.memberships),
                    "scope_ids": [scope.scope_id for scope in freeze.scopes],
                    "season": freeze.season,
                },
                "graph": {
                    "candidate_digest": candidate.digest,
                    "f16_manifest_digest": selected.f16_manifest_digest,
                    "selection_digest": selection_digest,
                },
                "policy": {**policy_value, "digest": policy.digest},
                "predecessor_digest": None,
                "profile": {
                    "digest": profile.digest,
                    "enabled_preference_ids": list(preferences),
                },
                "roles": {
                    "final_evaluation": None,
                    "fitting": None,
                    "validation": None,
                },
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "selection": {
                    "digest": selection_digest,
                    "completion_receipt_digest": selected.completion_receipt_digest,
                },
                "source_use": None,
            }
        except CaptureError:
            raise
        except (
            ArtifactError,
            MatchEvidenceCutoffError,
            MatchweekMembershipIntegrityError,
            MatchweekResearchError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise CaptureError("Exact selected graph failed capture-index construction.") from error

    def _source_use_decision(self, value: Mapping[str, Any]) -> SourceUseDecision:
        if self.source_authorizer is None:
            raise CaptureError("Real-source authorization is absent; live collection is refused.")
        freeze = value["freeze"]
        selection = value["selection"]
        profile = value["profile"]
        decision = self.source_authorizer.authorize_real_source_use(
            freeze_digest=freeze["digest"],
            selection_digest=selection["digest"],
            profile_digest=profile["digest"],
            scope_ids=tuple(freeze["scope_ids"]),
        )
        body = _read_protected_json(self.store, decision.decision_digest)
        if body != _source_use_binding(
            value,
            state=SourceUseState(decision.state).value,
            reason_codes=list(decision.reason_codes),
        ):
            raise CaptureError("Real-source authorization does not bind this exact selection.")
        return decision

    @staticmethod
    def _source_use_value(decision: SourceUseDecision) -> dict[str, Any]:
        return {
            "decision_digest": decision.decision_digest,
            "reason_codes": list(decision.reason_codes),
            "state": SourceUseState(decision.state).value,
        }

    def _apply_batch_result(
        self, value: dict[str, Any], rows: list[dict[str, Any]], result: BatchResult
    ) -> None:
        failures = [
            self._cb01_body(digest, "TimestampFailure") for digest in result.failure_digests
        ]
        batch = self._cb01_body(result.batch_digest, "FixtureEnrollmentBatch")
        first = rows[0]
        self._verify_batch_binding(value, first["membership_id"], batch)
        failure_reasons = sorted({reason for failure in failures for reason in failure["reasons"]})
        records: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        gen_time: str | None = None
        if result.publication_digest is not None:
            case = self.bootstrap.replay(result.publication_digest)
            verification = self._cb01_body(case.verification_digest, "TimestampVerification")
            tsa = verification.get("tsa")
            gen_time_value = tsa.get("gen_time_utc") if isinstance(tsa, Mapping) else None
            if not isinstance(gen_time_value, str):
                raise CaptureError("CB01 verified publication has no exact signed genTime.")
            member = next(row for row in rows if row["membership_id"] == first["membership_id"])
            kickoff = self._membership_kickoff(value, member["membership_id"])
            require_cb01_window(
                _time(gen_time_value, "CB01 signed genTime"),
                _time(value["chronology"]["common_T_utc"], "common T"),
                _time(kickoff, "F06 controlling kickoff"),
            )
            gen_time = gen_time_value
            records = {
                preference_id: (
                    digest,
                    str(record["disposition"]),
                    tuple(cast(list[str], record["reasons"])),
                )
                for preference_id, digest, record in case.records
            }
        for row in rows:
            preference_id = row["preference_id"]
            row["cb01"] = {
                "attempt_digest": result.attempt_digest,
                "batch_digest": result.batch_digest,
                "enrollment_digest": records.get(preference_id, (None, "", ()))[0],
                "failure_digests": list(result.failure_digests),
                "failure_reasons": failure_reasons,
                "gen_time_utc": gen_time,
                "publication_digest": result.publication_digest,
                "verification_digest": result.verification_digest,
            }
            if result.publication_digest is None:
                row["capture_state"] = (
                    CaptureState.FAILED.value
                    if result.failure_digests
                    else CaptureState.MISSING.value
                )
                row["capture_reasons"] = failure_reasons or ["CB01_RESULT_MISSING"]
            else:
                _, disposition, reasons = records[preference_id]
                row["capture_state"] = _capture_state_for_disposition(disposition).value
                row["capture_reasons"] = list(reasons)

    def _verify_rows(self, value: dict[str, Any]) -> None:
        rows = value.get("denominator_rows")
        if not isinstance(rows, list) or len(rows) != value["denominator"]["row_count"]:
            raise CaptureError("Capture index lost or duplicated a denominator row.")
        seen: set[tuple[str, str]] = set()
        verified_batch_digests: set[str] = set()
        verified_attempt_failures: dict[tuple[str, str], set[str]] = {}
        freeze = MatchweekMembershipRepository(self.store).get_by_id(value["freeze"]["freeze_id"])
        if freeze is None:
            raise CaptureError("Exact F06 freeze is unavailable during capture-index replay.")
        memberships = {item.membership_id: item for item in freeze.memberships}
        expected_excluded = [
            {
                "membership_digest": member.membership_digest,
                "membership_id": member.membership_id,
                "reason_code": member.reason_code,
                "reason_codes": list(member.reason_codes),
                "scope_id": member.scope_id,
            }
            for member in sorted(freeze.memberships, key=lambda item: item.membership_id)
            if member.decision.value != "INCLUDED"
        ]
        if value.get("excluded_memberships") != expected_excluded:
            raise CaptureError("Capture index changed exact excluded F06 membership reasons.")
        for row in rows:
            if not isinstance(row, dict):
                raise CaptureError("Capture denominator row is malformed.")
            membership_id = row.get("membership_id")
            preference_id = row.get("preference_id")
            if not isinstance(membership_id, str) or not isinstance(preference_id, str):
                raise CaptureError("Capture denominator pair identity is malformed.")
            key = (membership_id, preference_id)
            if key in seen:
                raise CaptureError("Capture index contains a duplicate denominator pair.")
            seen.add(key)
            member = memberships.get(membership_id)
            if (
                member is None
                or member.decision.value != "INCLUDED"
                or row.get("membership_state") != member.decision.value
            ):
                raise CaptureError("Capture denominator row is not an exact INCLUDED F06 member.")
            state_value = row.get("capture_state")
            if not isinstance(state_value, str):
                raise CaptureError("Capture row state is malformed.")
            state = CaptureState(state_value)
            if row.get("candidate_input", {}).get("state") != SupportState.UNKNOWN.value:
                raise CaptureError("Unsupported CandidateInput must remain UNKNOWN.")
            if row.get("outcome_state") not in {"MISSING", "PRESENT", "NOT_APPLICABLE"}:
                raise CaptureError("Capture row outcome availability state is malformed.")
            reasons = row.get("capture_reasons")
            if (
                not isinstance(reasons, list)
                or not reasons
                or any(not isinstance(reason, str) or not reason for reason in reasons)
            ):
                raise CaptureError("Capture denominator row lost its exact availability reasons.")
            cb01 = row.get("cb01")
            if not isinstance(cb01, dict):
                raise CaptureError("Capture row CB01 state is malformed.")
            batch_digest = cb01.get("batch_digest")
            if batch_digest is not None:
                if not isinstance(batch_digest, str):
                    raise CaptureError("CB01 batch identity is malformed.")
                if batch_digest not in verified_batch_digests:
                    self._verify_exact_batch(value, membership_id, batch_digest)
                    verified_batch_digests.add(batch_digest)
            if cb01.get("publication_digest") is not None:
                if state not in {
                    CaptureState.ENROLLED,
                    CaptureState.INCOMPLETE,
                    CaptureState.EXCLUDED,
                    CaptureState.UNSUPPORTED,
                }:
                    raise CaptureError("CB01 publication and denominator row state disagree.")
                case = self.bootstrap.replay(
                    cb01["publication_digest"],
                    tuple(
                        digest
                        for item in row["outcome_history"]
                        for digest in (
                            item["outcome_attachment_digest"],
                            item["fact_attachment_digest"],
                        )
                    ),
                )
                if case.batch_digest != cb01.get("batch_digest"):
                    raise CaptureError("CB01 publication differs from its exact indexed batch.")
                if case.verification_digest != cb01.get("verification_digest"):
                    raise CaptureError("Capture index changed its exact CB01 verification digest.")
                enrollment_rows = {
                    preference: (digest, record) for preference, digest, record in case.records
                }
                exact_enrollment = enrollment_rows.get(preference_id)
                if exact_enrollment is None or exact_enrollment[0] != cb01.get("enrollment_digest"):
                    raise CaptureError("CB01 enrollment differs from this exact preference row.")
                enrollment_record = exact_enrollment[1]
                expected_state = _capture_state_for_disposition(enrollment_record["disposition"])
                if (
                    state is not expected_state
                    or row["capture_reasons"] != enrollment_record["reasons"]
                ):
                    raise CaptureError(
                        "Capture row changed its exact CB01 enrollment state/reasons."
                    )
                verification = self._cb01_body(case.verification_digest, "TimestampVerification")
                tsa = verification.get("tsa")
                if not isinstance(tsa, Mapping) or tsa.get("gen_time_utc") != cb01.get(
                    "gen_time_utc"
                ):
                    raise CaptureError("Capture index changed the exact CB01 signed genTime.")
                require_cb01_window(
                    _time(tsa["gen_time_utc"], "CB01 signed genTime"),
                    _time(value["chronology"]["common_T_utc"], "common T"),
                    _time(self._membership_kickoff(value, membership_id), "kickoff"),
                )
                if row["outcome_history"]:
                    self._verify_outcomes(value, row, case.records)
            elif state is CaptureState.FAILED:
                if (
                    cb01.get("publication_digest") is not None
                    or not cb01.get("failure_digests")
                    or not isinstance(batch_digest, str)
                ):
                    raise CaptureError("Failed CB01 row has no exact failure artifact.")
                expected_reasons: set[str] = set()
                for digest in cb01["failure_digests"]:
                    failure = self._cb01_body(digest, "TimestampFailure")
                    if failure["batch_digest"] != cb01.get("batch_digest"):
                        raise CaptureError("CB01 failure differs from its exact batch.")
                    expected_reasons.update(failure["reasons"])
                if sorted(expected_reasons) != cb01.get("failure_reasons"):
                    raise CaptureError("Capture row changed exact CB01 failure reasons.")
                if row["capture_reasons"] != cb01.get("failure_reasons"):
                    raise CaptureError("Failed CB01 row changed its exact unavailable reasons.")
                for digest in cb01["failure_digests"]:
                    failure = self._cb01_body(digest, "TimestampFailure")
                    if (
                        failure.get("batch_digest") != batch_digest
                        or failure.get("expected_preference_ids")
                        != value["profile"]["enabled_preference_ids"]
                    ):
                        raise CaptureError("CB01 failure differs from its exact denominator batch.")
                    attempt_digest = failure.get("attempt_digest")
                    if attempt_digest is None:
                        if (
                            failure.get("attempt_result_digest") is not None
                            or failure.get("verification_digest") is not None
                        ):
                            raise CaptureError(
                                "CB01 failure has a result without its exact attempt."
                            )
                        continue
                    if not isinstance(attempt_digest, str):
                        raise CaptureError("CB01 failure attempt identity is malformed.")
                    attempt_key = (batch_digest, attempt_digest)
                    replayed_failures = verified_attempt_failures.get(attempt_key)
                    if replayed_failures is None:
                        replayed = self.bootstrap.resume(
                            batch_digest, attempt_digest, retry_failed=False
                        )
                        if (
                            replayed.batch_digest != batch_digest
                            or replayed.attempt_digest != attempt_digest
                        ):
                            raise CaptureError("CB01 failure attempt does not replay exactly.")
                        replayed_failures = set(replayed.failure_digests)
                        verified_attempt_failures[attempt_key] = replayed_failures
                    if digest not in replayed_failures:
                        raise CaptureError("CB01 failure is not the exact replayed attempt result.")
            elif state is CaptureState.MISSING:
                if (
                    cb01.get("publication_digest") is not None
                    or cb01.get("failure_digests")
                    or cb01.get("batch_digest") is None
                    or row["capture_reasons"] != ["CB01_RESULT_MISSING"]
                ):
                    raise CaptureError("Missing CB01 row changed its exact state or reason.")
            elif state is CaptureState.UNATTEMPTED:
                if cb01 != _empty_cb01() or row["capture_reasons"] != ["CB01_NOT_ATTEMPTED"]:
                    raise CaptureError("Unattempted CB01 row cannot have an enrollment batch.")
            elif state is CaptureState.WITHDRAWN:
                if value.get("source_use", {}).get("state") != SourceUseState.WITHDRAWN.value:
                    raise CaptureError("Withdrawn denominator row lacks exact source withdrawal.")
                if row["capture_reasons"] != value["source_use"].get("reason_codes"):
                    raise CaptureError("Withdrawn row lost exact source authorization reasons.")
                if cb01 != _empty_cb01():
                    raise CaptureError("Withdrawn row cannot retain a CB01 attempt or publication.")
            else:
                raise CaptureError("Capture row state lacks its exact CB01 result or refusal.")

            history = row.get("outcome_history")
            if not isinstance(history, list):
                raise CaptureError("Outcome history is malformed.")
            if bool(history) != (row["outcome_state"] == "PRESENT"):
                raise CaptureError("Outcome availability state differs from its exact history.")
            for sequence, item in enumerate(history):
                if item.get("correction_sequence") != sequence:
                    raise CaptureError("Outcome attachment history is not append-only.")
                expected_predecessor = (
                    history[sequence - 1]["outcome_attachment_digest"] if sequence else None
                )
                if item.get("predecessor_attachment_digest") != expected_predecessor:
                    raise CaptureError("Outcome attachment skipped its exact predecessor.")
        expected_pairs = {
            (member.membership_id, preference_id)
            for member in memberships.values()
            if member.decision.value == "INCLUDED"
            for preference_id in value["profile"]["enabled_preference_ids"]
        }
        if seen != expected_pairs:
            raise CaptureError(
                "Capture index denominator differs from exact INCLUDED F06 and Profile."
            )
        if value["denominator"] != {
            "included_membership_count": len(expected_pairs)
            // len(value["profile"]["enabled_preference_ids"]),
            "membership_count": len(expected_pairs)
            // len(value["profile"]["enabled_preference_ids"]),
            "preference_count": len(value["profile"]["enabled_preference_ids"]),
            "row_count": len(expected_pairs),
        }:
            raise CaptureError(
                "Capture index denominator counts differ from exact F06 and Profile."
            )

    def _verify_exact_batch(
        self, value: Mapping[str, Any], membership_id: str, batch_digest: str
    ) -> None:
        batch = self._cb01_body(batch_digest, "FixtureEnrollmentBatch")
        self._verify_batch_binding(value, membership_id, batch)
        try:
            prepared = replay_fixture_sources(self.store, batch)
            self.bootstrap._assert_prepared_batch(prepared, batch_digest, batch)
        except (
            ArtifactError,
            CB01Error,
            CB01SourceError,
            MatchEvidenceCutoffError,
            MatchweekMembershipIntegrityError,
            MatchweekResearchError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise CaptureError("Exact CB01 batch failed upstream lineage replay.") from error

    def _verify_batch_binding(
        self, value: Mapping[str, Any], membership_id: str, batch: Mapping[str, Any]
    ) -> None:
        rows = [row for row in value["denominator_rows"] if row["membership_id"] == membership_id]
        if not rows:
            raise CaptureError("CB01 batch membership is outside the exact denominator.")
        first = rows[0]
        anchor = batch.get("anchor")
        lineage = batch.get("lineage")
        expected_preferences = value["profile"]["enabled_preference_ids"]
        if (
            not isinstance(anchor, Mapping)
            or not isinstance(lineage, Mapping)
            or batch.get("expected_preference_ids") != expected_preferences
            or [row.get("preference_id") for row in rows] != expected_preferences
        ):
            raise CaptureError("CB01 batch differs from its exact full preference denominator.")

        def reference_matches(
            references: Mapping[str, Any],
            key: str,
            identity: str,
            digest: str,
        ) -> bool:
            reference = references.get(key)
            return (
                isinstance(reference, Mapping)
                and reference.get("state") == "PRESENT"
                and reference.get("id") == identity
                and reference.get("digest") == digest.removeprefix("sha256:")
            )

        expected_anchor = (
            reference_matches(
                anchor,
                "freeze",
                value["freeze"]["freeze_id"],
                value["freeze"]["digest"],
            )
            and reference_matches(
                anchor,
                "membership",
                membership_id,
                first["f06"]["membership_digest"],
            )
            and reference_matches(
                anchor,
                "cutoff",
                first["lineage"]["f07_cutoff_id"],
                first["lineage"]["f07_cutoff_digest"],
            )
            and reference_matches(
                anchor,
                "profile",
                value["profile"]["digest"],
                value["profile"]["digest"],
            )
            and anchor.get("membership", {}).get("id") == membership_id
            and _time(anchor.get("cutoff_utc"), "CB01 batch cutoff")
            == _time(value["chronology"]["common_T_utc"], "common T")
            and _time(anchor.get("kickoff_utc"), "CB01 batch kickoff")
            == _time(self._membership_kickoff(value, membership_id), "F06 controlling kickoff")
        )
        expected_lineage = all(
            (
                reference_matches(
                    lineage,
                    key,
                    identity,
                    digest,
                )
            )
            for key, identity, digest in (
                ("f06", value["freeze"]["freeze_id"], value["freeze"]["digest"]),
                (
                    "f07",
                    first["lineage"]["f07_cutoff_id"],
                    first["lineage"]["f07_cutoff_digest"],
                ),
                (
                    "f11_evidence",
                    first["lineage"]["f11_evidence_digest"],
                    first["lineage"]["f11_evidence_digest"],
                ),
                (
                    "f13_result",
                    first["lineage"]["f13_result_digest"],
                    first["lineage"]["f13_result_digest"],
                ),
                (
                    "f14_decision",
                    first["lineage"]["f14_decision_digest"],
                    first["lineage"]["f14_decision_digest"],
                ),
                (
                    "f14_profile",
                    value["profile"]["digest"],
                    value["profile"]["digest"],
                ),
                (
                    "f16_manifest",
                    value["graph"]["f16_manifest_digest"],
                    value["graph"]["f16_manifest_digest"],
                ),
                (
                    "f16_match_result",
                    first["lineage"]["f16_match_result_digest"],
                    first["lineage"]["f16_match_result_digest"],
                ),
            )
        )
        causal = lineage.get("causal_selection")
        exact_causal_selection = (
            isinstance(causal, Mapping)
            and causal.get("selection_digest") == value["selection"]["digest"]
            and causal.get("completion_receipt_digest")
            == value["selection"]["completion_receipt_digest"]
            and causal.get("candidate_contract_digest") == value["graph"]["candidate_digest"]
        )
        if not expected_anchor or not expected_lineage or not exact_causal_selection:
            raise CaptureError("CB01 batch differs from the exact selected freeze or graph.")

    def _verify_outcomes(
        self,
        value: Mapping[str, Any],
        row: Mapping[str, Any],
        case_records: tuple[tuple[str, str, dict[str, Any]], ...],
    ) -> None:
        enrollment_by_preference = {
            preference_id: digest for preference_id, digest, _ in case_records
        }
        expected_enrollment = enrollment_by_preference.get(row["preference_id"])
        if expected_enrollment != row["cb01"]["enrollment_digest"]:
            raise CaptureError("F19 outcome does not name this row's exact CB01 enrollment.")
        for sequence, item in enumerate(row["outcome_history"]):
            settlement = (
                SettlementRepository(self.store).replay(item["settlement_digest"]).to_dict()
            )
            if (
                settlement.get("selection_digest") != value["selection"]["digest"]
                or settlement.get("manifest_digest") != value["graph"]["f16_manifest_digest"]
                or settlement.get("match_result_digest")
                != row["lineage"]["f16_match_result_digest"]
                or settlement.get("preference_id") != row["preference_id"]
            ):
                raise CaptureError(
                    "Attached F19 settlement no longer matches the exact denominator row."
                )
            _require_source_backed_post_kickoff(
                settlement,
                _time(
                    self._membership_kickoff(value, row["membership_id"]),
                    "F06 controlling kickoff",
                ),
            )
            attachment = self._cb01_body(item["outcome_attachment_digest"], "OutcomeAttachment")
            fact = self._cb01_body(item["fact_attachment_digest"], "OutcomeFactAttachment")
            expected_settlement_predecessor = (
                row["outcome_history"][sequence - 1]["settlement_digest"] if sequence else None
            )
            expected_attachment_predecessor = (
                row["outcome_history"][sequence - 1]["outcome_attachment_digest"]
                if sequence
                else None
            )
            expected_fact_predecessor = (
                row["outcome_history"][sequence - 1]["fact_attachment_digest"] if sequence else None
            )
            if (
                settlement.get("correction_sequence") != sequence
                or settlement.get("predecessor_digest") != expected_settlement_predecessor
                or attachment["enrollment_digest"] != expected_enrollment
                or attachment["settlement_digest"] != item["settlement_digest"]
                or attachment["correction_sequence"] != sequence
                or attachment["predecessor_digest"] != expected_attachment_predecessor
                or fact["settlement_digest"] != item["settlement_digest"]
                or fact["enrollment_digest"] != expected_enrollment
                or fact["correction_sequence"] != sequence
                or fact["predecessor_digest"] != expected_fact_predecessor
                or attachment["fact_attachment_digest"] != item["fact_attachment_digest"]
                or item["source_provenance"] != _source_provenance(settlement)
            ):
                raise CaptureError("Exact F19 outcome facts or lineage differ from the index.")

    def _cb01_body(self, digest: str, kind: str) -> dict[str, Any]:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            CB01_MEDIA_TYPES[kind],
            "PROTECTED",
        ):
            raise CaptureError(f"Exact protected CB01 {kind} artifact is unavailable.")
        try:
            _, body = decode_artifact(self.artifacts.read_artifact(digest), expected_kind=kind)
            return body
        except (TypeError, ValueError) as error:
            raise CaptureError(f"Exact CB01 {kind} artifact failed replay.") from error

    def _membership_kickoff(self, value: Mapping[str, Any], membership_id: str) -> str:
        freeze = MatchweekMembershipRepository(self.store).get_by_id(value["freeze"]["freeze_id"])
        if freeze is None:
            raise CaptureError("Exact F06 freeze is unavailable during CB01 replay.")
        member = next(
            (item for item in freeze.memberships if item.membership_id == membership_id), None
        )
        if member is None or member.controlling_revision.kickoff_utc is None:
            raise CaptureError("Exact F06 controlling kickoff is unavailable.")
        return member.controlling_revision.kickoff_utc

    def _denominator_row(
        self, value: dict[str, Any], membership_id: str, preference_id: str
    ) -> dict[str, Any]:
        matches = [
            row
            for row in value["denominator_rows"]
            if row["membership_id"] == membership_id and row["preference_id"] == preference_id
        ]
        if len(matches) != 1:
            raise CaptureError("Exact denominator membership/preference pair is unavailable.")
        row = matches[0]
        if not isinstance(row, dict):
            raise CaptureError("Exact denominator row is malformed.")
        return cast(dict[str, Any], row)

    def _publish(self, value: dict[str, Any]) -> CaptureIndex:
        encoded = canonical_json(value).encode("utf-8")
        record = self.artifacts.publish_artifact(
            encoded, CAPTURE_INDEX_MEDIA_TYPE, retention_class="PROTECTED"
        )
        if record.digest != _digest(encoded):
            raise CaptureError("Capture index artifact digest changed during publication.")
        return CaptureIndex(encoded)

    @staticmethod
    def _successor_value(value: dict[str, Any], predecessor_digest: str) -> dict[str, Any]:
        successor = json.loads(canonical_json(value))
        successor["predecessor_digest"] = predecessor_digest
        return cast(dict[str, Any], successor)


def require_pre_t_witness(upper_bound: datetime, common_t: datetime) -> None:
    """Require the #80 signed upper bound to be strictly earlier than common T."""
    if upper_bound.tzinfo is None or common_t.tzinfo is None:
        raise CaptureError("Chronology bounds must carry explicit UTC offsets.")
    if upper_bound.astimezone(UTC) >= common_t.astimezone(UTC):
        raise CaptureError("The signed #80 upper bound must be strictly before common T.")


def require_cb01_window(gen_time: datetime, common_t: datetime, kickoff: datetime) -> None:
    """Require CB01's independent strict T < signed genTime < own kickoff window."""
    if any(item.tzinfo is None for item in (gen_time, common_t, kickoff)):
        raise CaptureError("CB01 chronology values must carry explicit UTC offsets.")
    signed = gen_time.astimezone(UTC)
    if signed <= common_t.astimezone(UTC):
        raise CaptureError("CB01 signed genTime must be strictly after common T.")
    if signed >= kickoff.astimezone(UTC):
        raise CaptureError("CB01 signed genTime must be strictly before kickoff.")


def _require_diagnostic_policy(policy: PolicyVersion) -> None:
    if (
        policy.mode is not PolicyStatus.RESEARCH_ONLY
        or policy.thresholds
        or policy.selection_strength is not None
        or policy.correlation_groups
        or policy.user_preference_order
        or policy.dependencies
        or policy.promotion_evidence
    ):
        raise CaptureError("Capture requires an explicit diagnostic RESEARCH_ONLY policy.")


def _expected_scopes(friday: str, season: str) -> tuple[Any, ...]:
    from matchvet.fixture_coverage import fixture_scopes_for_matchweek

    return fixture_scopes_for_matchweek(friday, season=season)


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise CaptureError(f"{label} is missing its exact timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CaptureError(f"{label} is malformed.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CaptureError(f"{label} must carry an explicit UTC offset.")
    return parsed.astimezone(UTC)


def _read_protected_json(store: Store, digest: str) -> dict[str, Any]:
    metadata = store.artifact_metadata(digest)
    if metadata is None or metadata.retention_class != "PROTECTED":
        raise CaptureError("Exact upstream artifact is missing or not protected.")
    try:
        content = ArtifactStore(store).read_artifact(digest)
        value = json.loads(content)
    except (ArtifactError, TypeError, ValueError) as error:
        raise CaptureError("Exact upstream artifact is not valid JSON.") from error
    if not isinstance(value, dict) or canonical_json(value).encode("utf-8") != content:
        raise CaptureError("Exact upstream JSON artifact is not canonical.")
    return value


def _same_base_identity(value: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for key in (
        "schema_version",
        "contract",
        "freeze",
        "profile",
        "selection",
        "graph",
        "chronology",
        "policy",
        "denominator",
        "excluded_memberships",
        "roles",
    ):
        if value.get(key) != expected.get(key):
            raise CaptureError(f"Capture index changed exact immutable {key} lineage.")
    expected_rows = {
        (row["membership_id"], row["preference_id"]): row for row in expected["denominator_rows"]
    }
    rows = value.get("denominator_rows")
    if not isinstance(rows, list) or len(rows) != len(expected_rows):
        raise CaptureError("Capture index does not preserve the original full denominator.")
    for row in rows:
        identity = (row.get("membership_id"), row.get("preference_id"))
        base = expected_rows.get(identity)
        if base is None:
            raise CaptureError("Capture index contains a pair outside F06 and Profile.")
        for key in (
            "f06",
            "f13",
            "f14",
            "lineage",
            "membership_id",
            "membership_state",
            "preference_id",
            "scope_id",
            "candidate_input",
        ):
            if row.get(key) != base.get(key):
                raise CaptureError("Capture successor changed an exact upstream denominator row.")


def _empty_cb01() -> dict[str, Any]:
    return {
        "attempt_digest": None,
        "batch_digest": None,
        "enrollment_digest": None,
        "failure_digests": [],
        "failure_reasons": [],
        "gen_time_utc": None,
        "publication_digest": None,
        "verification_digest": None,
    }


def _source_provenance(settlement: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = settlement.get("evidence")
    if not isinstance(evidence, list):
        raise CaptureError("Exact F19 source evidence snapshot is malformed.")
    return [
        {
            "evidence_digest": item.get("evidence_digest"),
            "fixture_status": item.get("fixture_status"),
            "observed_at_utc": item.get("observed_at_utc"),
            "published_at_utc": item.get("published_at_utc"),
            "record_id": item.get("record_id"),
            "retrieved_at_utc": item.get("retrieved_at_utc"),
            "source_digest": item.get("source_digest"),
            "source_key": item.get("source_key"),
            "source_level": item.get("source_level"),
        }
        for item in evidence
    ]


def _require_source_backed_post_kickoff(settlement: Mapping[str, Any], kickoff: datetime) -> None:
    if settlement.get("state") == "PENDING":
        raise CaptureError("F19 PENDING settlement cannot be attached as a post-play outcome.")
    evidence = settlement.get("evidence")
    if (
        not isinstance(evidence, list)
        or not evidence
        or any(
            not isinstance(item, Mapping)
            or not item.get("source_key")
            or not item.get("record_id")
            or not item.get("evidence_digest")
            or not _is_source_digest(item.get("source_digest"))
            for item in evidence
        )
    ):
        raise CaptureError("F19 outcome lacks exact source-backed evidence digests.")
    for item in evidence:
        assert isinstance(item, Mapping)
        times = [
            _time(item[key], f"F19 source {key}")
            for key in ("published_at_utc", "observed_at_utc", "retrieved_at_utc")
            if item.get(key) is not None
        ]
        if not times or not any(timestamp > kickoff for timestamp in times):
            raise CaptureError(
                "F19 source evidence must have an exact publication, observation, or availability "
                "time strictly after the controlling kickoff."
            )


def _source_use_binding(
    value: Mapping[str, Any], *, state: object, reason_codes: object
) -> dict[str, Any]:
    if not isinstance(state, str) or state not in {item.value for item in SourceUseState}:
        raise CaptureError("Source-use decision state is malformed.")
    if not isinstance(reason_codes, list) or any(
        not isinstance(reason, str) or not reason for reason in reason_codes
    ):
        raise CaptureError("Source-use decision reasons are malformed.")
    if reason_codes != sorted(set(reason_codes)):
        raise CaptureError("Source-use decision reasons are noncanonical.")
    if (state == SourceUseState.APPROVED.value) != (len(reason_codes) == 0):
        raise CaptureError("Source-use decision state and reasons disagree.")
    return {
        "contract": SOURCE_USE_DECISION_CONTRACT,
        "freeze_digest": value["freeze"]["digest"],
        "profile_digest": value["profile"]["digest"],
        "reason_codes": reason_codes,
        "scope_ids": value["freeze"]["scope_ids"],
        "selection_digest": value["selection"]["digest"],
        "state": state,
    }


def _capture_state_for_disposition(disposition: object) -> CaptureState:
    if not isinstance(disposition, str):
        return CaptureState.UNSUPPORTED
    return _CB01_CAPTURE_STATES.get(disposition, CaptureState.UNSUPPORTED)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_source_digest(value: object) -> bool:
    if not isinstance(value, str):
        return False
    hex_digest = value.removeprefix("sha256:")
    return len(hex_digest) == 64 and all(
        character in "0123456789abcdef" for character in hex_digest
    )

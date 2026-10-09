"""Immutable V2 settlements bound to exact F16 and F14 artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.f14 import DecisionRepository, F14Error
from matchvet.f16 import (
    CAUSAL_MANIFEST_MEDIA_TYPE,
    F16Error,
    F16MatchweekProcessor,
)
from matchvet.f16 import MANIFEST_MEDIA_TYPE as LEGACY_MANIFEST_MEDIA_TYPE
from matchvet.matchweek_membership import canonical_json
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    MatchweekResearchError,
    MatchweekResearchRepository,
    _logical_identity,
)
from matchvet.research_identity import completion_slot, selection_slot
from matchvet.store import Store
from matchvet.t10 import (
    DEFAULT_PREFERENCE_CATALOG,
    BettingPreference,
    GradingState,
    SettlementEvidence,
    SettlementGrade,
    SettlementGrader,
    SettlementResult,
    T10Error,
)

SETTLEMENT_MEDIA_TYPE = "application/vnd.matchvet.f19-settlement.v1+json"
CAUSAL_SETTLEMENT_MEDIA_TYPE = "application/vnd.matchvet.f19-settlement.v2+json"
SCHEMA_VERSION = 1
CAUSAL_SCHEMA_VERSION = 2
_CAUSAL_IDENTITY_KEYS = {
    "selection_digest",
    "completion_receipt_digest",
    "candidate_contract_digest",
    "candidate_contract_version",
    "engine_contract_digest",
    "engine_version",
    "selection_reader_version_id",
    "selection_reader_definition_id",
    "selection_reader_name",
    "selection_reader_content_digest",
    "selection_reader_contract_version",
}


class F19Error(ValueError):
    """An F19 settlement input or protected artifact failed validation."""


class SettlementState(StrEnum):
    PENDING = "PENDING"
    CONFLICTING = "CONFLICTING"
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"
    VOID = "VOID"


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class SettlementRecord:
    """One immutable settlement version for one F16 match and F14 preference."""

    canonical_bytes: bytes

    @property
    def digest(self) -> str:
        return _digest(self.canonical_bytes)

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical_bytes))

    @property
    def state(self) -> SettlementState:
        return SettlementState(self.to_dict()["state"])

    @property
    def settlement_result(self) -> SettlementResult | None:
        raw = self.to_dict()["settlement_result"]
        return SettlementResult(raw) if raw is not None else None

    @property
    def predecessor_digest(self) -> str | None:
        return cast(str | None, self.to_dict()["predecessor_digest"])

    @property
    def correction_sequence(self) -> int:
        return cast(int, self.to_dict()["correction_sequence"])

    @property
    def evidence_digest(self) -> str:
        return cast(str, self.to_dict()["evidence_digest"])


class SettlementRepository:
    """Build, correct, and replay protected settlement versions without DB migrations."""

    def __init__(self, store: Store, grader: SettlementGrader | None = None) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)
        self.grader = grader or SettlementGrader()
        self._lineage_cache: dict[
            tuple[str, str, str], tuple[dict[str, str], str, BettingPreference]
        ] = {}

    def build(
        self,
        manifest_digest: str,
        match_result_digest: str,
        preference_id: str,
        evidence: Iterable[SettlementEvidence],
        *,
        predecessor_digest: str | None = None,
    ) -> SettlementRecord:
        """Build an idempotent version; changed evidence needs an explicit predecessor."""
        identity, fixture_id, preference = self._lineage(
            manifest_digest, match_result_digest, preference_id
        )
        records = self._evidence(evidence, fixture_id)
        grade = self.grader.grade(preference, records, fixture_id=fixture_id)
        state = _state_for(grade)

        previous: SettlementRecord | None = None
        if predecessor_digest is not None:
            previous = self.replay(predecessor_digest)
            if _identity(previous.to_dict()) != identity:
                raise F19Error("Settlement correction cannot change exact frozen lineage.")
            previous_grade = SettlementGrade.from_dict(previous.to_dict()["grade"])
            if previous_grade.evidence_digest == grade.evidence_digest and previous.state is state:
                return previous
            successors = self._successors(predecessor_digest)
            for successor in successors:
                successor_grade = SettlementGrade.from_dict(successor.to_dict()["grade"])
                if (
                    successor_grade.evidence_digest == grade.evidence_digest
                    and successor.state is state
                ):
                    return successor
            if successors:
                raise F19Error("Settlement predecessor already has a different successor.")
            sequence = previous.correction_sequence + 1
        else:
            sequence = 0
            existing = self._versions(identity)
            if existing:
                for record in existing:
                    value = record.to_dict()
                    stored_grade = SettlementGrade.from_dict(value["grade"])
                    if stored_grade.evidence_digest == grade.evidence_digest:
                        return record
                raise F19Error("Changed settlement evidence requires its predecessor digest.")

        value = {
            **identity,
            "fixture_id": fixture_id,
            "correction_sequence": sequence,
            "evidence": [item.to_dict() for item in records],
            "evidence_digest": grade.evidence_digest,
            "grade": grade.to_dict(),
            "predecessor_digest": previous.digest if previous is not None else None,
            "schema_version": (
                CAUSAL_SCHEMA_VERSION if "selection_digest" in identity else SCHEMA_VERSION
            ),
            "settlement_result": grade.settlement_result.value
            if grade.settlement_result is not None
            else None,
            "state": state.value,
        }
        content = _bytes(value)
        media_type = (
            CAUSAL_SETTLEMENT_MEDIA_TYPE
            if "selection_digest" in identity
            else SETTLEMENT_MEDIA_TYPE
        )
        published = self.artifacts.publish_artifact(content, media_type)
        return self._replay(published.digest)

    def replay(self, digest: str) -> SettlementRecord:
        """Verify a settlement artifact, exact lineage, evidence, and deterministic grade."""
        return self._replay(digest)

    def correct(
        self, predecessor_digest: str, evidence: Iterable[SettlementEvidence]
    ) -> SettlementRecord:
        """Append a complete evidence snapshot as a successor of one exact version."""
        predecessor = self.replay(predecessor_digest)
        value = predecessor.to_dict()
        return self.build(
            value["manifest_digest"],
            value["match_result_digest"],
            value["preference_id"],
            evidence,
            predecessor_digest=predecessor.digest,
        )

    def _replay(self, digest: str) -> SettlementRecord:
        try:
            metadata = self.store.artifact_metadata(digest)
            if (
                metadata is None
                or metadata.media_type
                not in {
                    SETTLEMENT_MEDIA_TYPE,
                    CAUSAL_SETTLEMENT_MEDIA_TYPE,
                }
                or metadata.retention_class != "PROTECTED"
            ):
                raise F19Error("Missing or wrong protected F19 settlement artifact.")
            content = self.artifacts.read_artifact(digest)
            value = json.loads(content)
            if (
                not isinstance(value, dict)
                or _bytes(value) != content
                or _digest(content) != digest
            ):
                raise F19Error("F19 settlement artifact is malformed or noncanonical.")
            causal = metadata.media_type == CAUSAL_SETTLEMENT_MEDIA_TYPE
            expected_keys = {
                "manifest_digest",
                "match_result_digest",
                "decision_digest",
                "preference_id",
                "fixture_id",
                "correction_sequence",
                "evidence",
                "evidence_digest",
                "grade",
                "predecessor_digest",
                "schema_version",
                "settlement_result",
                "state",
            }
            if causal:
                expected_keys |= _CAUSAL_IDENTITY_KEYS
            if set(value) != expected_keys or type(value["schema_version"]) is not int:
                raise F19Error("F19 settlement artifact schema is invalid.")
            if value["schema_version"] != (CAUSAL_SCHEMA_VERSION if causal else SCHEMA_VERSION):
                raise F19Error("Unsupported F19 settlement schema.")
            identity, fixture_id, preference = self._lineage(
                value["manifest_digest"],
                value["match_result_digest"],
                value["preference_id"],
                historical_inspection=causal,
            )
            if _identity(value) != identity or value["fixture_id"] != fixture_id:
                raise F19Error("F19 settlement identity differs from exact F16/F14 lineage.")
            evidence_value = value["evidence"]
            if not isinstance(evidence_value, list) or not all(
                isinstance(item, Mapping) for item in evidence_value
            ):
                raise F19Error("F19 source evidence is malformed.")
            records = self._evidence(
                (SettlementEvidence.from_mapping(item) for item in evidence_value), fixture_id
            )
            if _bytes([item.to_dict() for item in records]) != _bytes(evidence_value):
                raise F19Error("F19 source evidence is not canonical.")
            grade = self.grader.grade(preference, records, fixture_id=fixture_id)
            if (
                _bytes(value["grade"]) != _bytes(grade.to_dict())
                or value["evidence_digest"] != grade.evidence_digest
                or value["state"] != _state_for(grade).value
                or value["settlement_result"]
                != (grade.settlement_result.value if grade.settlement_result is not None else None)
            ):
                raise F19Error("F19 settlement does not match deterministic T10 grading.")
            sequence = value["correction_sequence"]
            predecessor_digest = value["predecessor_digest"]
            if type(sequence) is not int or sequence < 0:
                raise F19Error("F19 correction sequence is invalid.")
            if predecessor_digest is None:
                if sequence != 0:
                    raise F19Error("Initial F19 settlement has a correction sequence.")
            else:
                predecessor = self._replay(predecessor_digest)
                if (
                    _identity(predecessor.to_dict()) != identity
                    or sequence != predecessor.correction_sequence + 1
                ):
                    raise F19Error("F19 correction predecessor is invalid.")
            return SettlementRecord(content)
        except F19Error:
            raise
        except (
            ArtifactError,
            F14Error,
            F16Error,
            T10Error,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise F19Error("Malformed or invalid F19 settlement lineage.") from error

    def _lineage(
        self,
        manifest_digest: str,
        match_result_digest: str,
        preference_id: str,
        *,
        historical_inspection: bool = False,
    ) -> tuple[dict[str, str], str, BettingPreference]:
        metadata = self.store.artifact_metadata(manifest_digest)
        if (
            metadata is None
            or metadata.retention_class != "PROTECTED"
            or metadata.media_type not in {LEGACY_MANIFEST_MEDIA_TYPE, CAUSAL_MANIFEST_MEDIA_TYPE}
        ):
            raise F19Error("Exact protected F16 manifest is unavailable for settlement.")
        try:
            manifest_content = self.artifacts.read_artifact(manifest_digest)
            manifest_value = json.loads(manifest_content)
            if not isinstance(manifest_value, dict) or _bytes(manifest_value) != manifest_content:
                raise F19Error("F16 manifest is malformed or noncanonical for settlement.")
        except F19Error:
            raise
        except (ArtifactError, TypeError, ValueError) as error:
            raise F19Error("Exact protected F16 manifest cannot be read for settlement.") from error
        owner = MatchweekResearchRepository(self.store)
        if metadata.media_type == CAUSAL_MANIFEST_MEDIA_TYPE and owner.is_corrected(
            manifest_value["cutoff_policy_digest"]
        ):
            try:
                freeze = MatchweekMembershipRepository(self.store).get_by_id(
                    manifest_value["freeze_id"]
                )
                if freeze is None:
                    raise F19Error("Causal F16 references a missing exact F06 freeze.")
                logical = _logical_identity(freeze.season, freeze.matchweek_friday)
                selection_digest = self.store.snapshot_manifest_digest_for_snapshot(
                    selection_slot(logical)
                )
                if selection_digest is None:
                    raise F19Error("Causal settlement requires an exact selected owner state.")
                from matchvet.causal_dispatch import (
                    inspect_causal_selection,
                    resolve_qualified_causal_selection,
                )

                selected = (
                    inspect_causal_selection(self.store, selection_digest)
                    if historical_inspection
                    else resolve_qualified_causal_selection(self.store, selection_digest)
                )
            except MatchweekResearchError as error:
                raise F19Error("Corrected settlement selected lineage failed replay.") from error
            if selected.f16_manifest_digest != manifest_digest:
                raise F19Error("Corrected settlement requires the exact selected F16 manifest.")
            logical = _logical_identity(freeze.season, freeze.matchweek_friday)
            receipt_digest = self.store.snapshot_manifest_digest_for_snapshot(
                completion_slot(logical)
            )
            if receipt_digest is None or selected.completion_receipt_digest != receipt_digest:
                raise F19Error("Causal settlement requires the exact retained completion receipt.")
            causal_identity = {
                "selection_digest": selected.selection_digest,
                "completion_receipt_digest": selected.completion_receipt_digest,
                "candidate_contract_digest": selected.candidate_contract_digest,
                "candidate_contract_version": selected.candidate.contract_version,
                "engine_contract_digest": selected.engine_contract_digest,
                "engine_version": selected.engine_version,
                "selection_reader_version_id": selected.selection_reader.version_id.value,
                "selection_reader_definition_id": selected.selection_reader.definition_id.value,
                "selection_reader_name": selected.selection_reader.name,
                "selection_reader_content_digest": selected.selection_reader.content_sha256,
                "selection_reader_contract_version": str(
                    selected.selection_reader.canonical_contract_version
                ),
            }
        elif owner.is_corrected(manifest_value["cutoff_policy_digest"]):
            if metadata.media_type == CAUSAL_MANIFEST_MEDIA_TYPE:
                raise F19Error("Causal F16 requires the corrected common-cutoff policy.")
            try:
                selected_v1 = owner.selected_for_boundary(
                    manifest_value["freeze_id"], manifest_value["cutoff_policy_digest"]
                )
            except MatchweekResearchError as error:
                raise F19Error("Corrected settlement selected lineage failed replay.") from error
            if selected_v1 is None or selected_v1.f16_manifest_digest != manifest_digest:
                raise F19Error("Corrected settlement requires the exact selected F16 manifest.")
            causal_identity = {}
        else:
            if metadata.media_type == CAUSAL_MANIFEST_MEDIA_TYPE:
                raise F19Error("Causal F16 settlement requires exact corrected qualification.")
            causal_identity = {}

        cache_key = (manifest_digest, match_result_digest, preference_id)
        cached = self._lineage_cache.get(cache_key)
        if cached is not None:
            identity, fixture_id, preference = cached
            match_values = manifest_value.get("matches")
            exact_matches = (
                [
                    row
                    for row in match_values
                    if isinstance(row, dict)
                    and row.get("match_result_digest") == match_result_digest
                ]
                if isinstance(match_values, list)
                else []
            )
            expected_identity = {
                **causal_identity,
                "decision_digest": (
                    exact_matches[0].get("decision_digest") if len(exact_matches) == 1 else None
                ),
                "manifest_digest": manifest_digest,
                "match_result_digest": match_result_digest,
                "preference_id": preference_id,
            }
            if (
                len(exact_matches) != 1
                or identity != expected_identity
                or exact_matches[0].get("decision_digest") is None
            ):
                raise F19Error("Cached settlement lineage differs from the exact selected origin.")
            try:
                for digest in (
                    manifest_digest,
                    match_result_digest,
                    identity["decision_digest"],
                    exact_matches[0].get("evidence_digest", ""),
                    exact_matches[0].get("model_digest", ""),
                ):
                    self.artifacts.verify_artifact(digest)
                preference = DEFAULT_PREFERENCE_CATALOG.get(preference_id)
                if _bytes(preference.to_dict()) != _bytes(cached[2].to_dict()):
                    raise F19Error("Cached F14 preference differs from the exact T10 catalog.")
                match_content = self.artifacts.read_artifact(match_result_digest)
                match_value = json.loads(match_content)
                decision_content = self.artifacts.read_artifact(identity["decision_digest"])
                decision_value = json.loads(decision_content)
                if (
                    not isinstance(match_value, dict)
                    or _bytes(match_value) != match_content
                    or match_value.get("decision_digest") != identity["decision_digest"]
                    or match_value.get("fixture_id") != fixture_id
                    or not isinstance(decision_value, dict)
                    or _bytes(decision_value) != decision_content
                    or decision_value.get("fixture_id") != fixture_id
                ):
                    raise F19Error("Cached F16/F14 fixtures differ from the exact lineage.")
                decision_rows = decision_value.get("preference_results")
                stored_preference = (
                    next(
                        (
                            row["vetting"]["preference"]
                            for row in decision_rows
                            if isinstance(row, dict)
                            and isinstance(row.get("vetting"), dict)
                            and row["vetting"].get("preference", {}).get("preference_id")
                            == preference_id
                        ),
                        None,
                    )
                    if isinstance(decision_rows, list)
                    else None
                )
                if stored_preference is None or _bytes(stored_preference) != _bytes(
                    preference.to_dict()
                ):
                    raise F19Error("Cached F14 preference differs from its exact decision.")
            except ArtifactError as error:
                raise F19Error(
                    "Cached F16/F14 settlement lineage failed artifact verification."
                ) from error
            except F19Error:
                raise
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise F19Error("Cached F16/F14 settlement lineage is malformed.") from error
            return cached

        try:
            manifest = F16MatchweekProcessor(self.store).replay_manifest(manifest_digest)
        except (ArtifactError, F16Error, ValueError) as error:
            raise F19Error(
                "Settlement requires exact replay of the selected F16 manifest."
            ) from error
        if manifest.to_dict() != manifest_value:
            raise F19Error("F16 replay differs from its exact protected manifest bytes.")
        match = next(
            (
                row
                for row in manifest.match_results
                if row.match_result_digest == match_result_digest
            ),
            None,
        )
        if match is None:
            raise F19Error("F16 manifest does not contain the exact match result.")
        decision = DecisionRepository(self.store).replay(match.decision_digest)
        decision_value = decision.to_dict()
        rows = decision_value["preference_results"]
        match_preference = next(
            (
                row["vetting"]["preference"]
                for row in rows
                if row["vetting"]["preference"]["preference_id"] == preference_id
            ),
            None,
        )
        if match_preference is None:
            raise F19Error("Preference is not enabled in the exact F14 decision.")
        try:
            preference = DEFAULT_PREFERENCE_CATALOG.get(preference_id)
        except (KeyError, ValueError) as error:
            raise F19Error("F14 preference is not supported by T10 settlement rules.") from error
        if _bytes(preference.to_dict()) != _bytes(match_preference):
            raise F19Error("F14 preference contract differs from the exact T10 catalog.")
        result = (
            {
                **causal_identity,
                "decision_digest": match.decision_digest,
                "manifest_digest": manifest_digest,
                "match_result_digest": match_result_digest,
                "preference_id": preference_id,
            },
            cast(str, decision_value["fixture_id"]),
            preference,
        )
        cached = self._lineage_cache.get(cache_key)
        if cached is not None and cached != result:
            raise F19Error("Cached settlement lineage differs from the exact selected origin.")
        self._lineage_cache[cache_key] = result
        return result

    def _evidence(
        self, evidence: Iterable[SettlementEvidence], fixture_id: str
    ) -> tuple[SettlementEvidence, ...]:
        values = tuple(evidence)
        if any(not isinstance(item, SettlementEvidence) for item in values):
            raise F19Error("F19 accepts T10 source evidence records, not manual grades.")
        if any(item.fixture_id != fixture_id for item in values):
            raise F19Error("F19 source evidence identifies another fixture.")
        if any(_contains_odds(item.to_dict()) for item in values):
            raise F19Error("Bookmaker odds are not accepted by F19 settlement evidence.")
        return tuple(
            sorted(
                {item.evidence_id: item for item in values}.values(), key=lambda x: x.evidence_id
            )
        )

    def _versions(self, identity: Mapping[str, str]) -> tuple[SettlementRecord, ...]:
        records: list[SettlementRecord] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type in {SETTLEMENT_MEDIA_TYPE, CAUSAL_SETTLEMENT_MEDIA_TYPE}:
                record = self._replay(metadata.digest)
                if _identity(record.to_dict()) == identity:
                    records.append(record)
        return tuple(records)

    def _successors(self, digest: str) -> tuple[SettlementRecord, ...]:
        return tuple(
            record
            for record in self._versions(_identity(self._replay(digest).to_dict()))
            if record.predecessor_digest == digest
        )


def _identity(value: Mapping[str, object]) -> dict[str, str]:
    identity = {
        "manifest_digest": cast(str, value["manifest_digest"]),
        "match_result_digest": cast(str, value["match_result_digest"]),
        "decision_digest": cast(str, value["decision_digest"]),
        "preference_id": cast(str, value["preference_id"]),
    }
    if "selection_digest" in value:
        identity.update({key: cast(str, value[key]) for key in _CAUSAL_IDENTITY_KEYS})
    return identity


def _state_for(grade: SettlementGrade) -> SettlementState:
    if grade.grading_state is GradingState.PENDING:
        return (
            SettlementState.CONFLICTING
            if grade.reason_code == "SOURCE_CONFLICT"
            else SettlementState.PENDING
        )
    if grade.settlement_result is None:
        raise F19Error("A final T10 grade has no settlement result.")
    return SettlementState(grade.settlement_result.value)


def _contains_odds(value: object) -> bool:
    if isinstance(value, Mapping):
        forbidden = {"odds", "price", "bookmaker", "stake", "profit", "volume"}
        return any(
            str(key).casefold() in forbidden or _contains_odds(item) for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_odds(item) for item in value)
    return False

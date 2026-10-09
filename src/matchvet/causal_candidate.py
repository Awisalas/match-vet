"""Canonical unqualified candidate identity and exact historical/successor dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import freeze_payload
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import CORRECTED_RULE, MatchweekResearchError, _logical_identity

if TYPE_CHECKING:
    from matchvet.matchweek_research import MatchweekResearchRepository
    from matchvet.store import Store
    from matchvet.t15 import PolicyVersion
    from matchvet.weather import WeatherRequest

CAUSAL_CONTRACT = "matchvet-causal-selection-v2"
HISTORICAL_CONTRACT = "postcommit-upper-bound-v1"
CANDIDATE_MEDIA_TYPE = "application/vnd.matchvet.causal-candidate.v1+json"
ENGINE_MEDIA_TYPE = "application/vnd.matchvet.causal-engine.v1+json"
POLICY_MEDIA_TYPE = "application/vnd.matchvet.causal-decision-policy.v1+json"
FREEZE_MEDIA_TYPE = "application/vnd.matchvet.f06-freeze-canonical.v1+json"
RUN_CONTRACT = "MATCHVET_V2_ANALYZE_MATCHWEEK_CAUSAL_V2"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise MatchweekResearchError("An explicit canonical candidate contract digest is required.")


@dataclass(frozen=True)
class CausalCandidateContract:
    schema_version: int
    contract_version: str
    logical_matchweek_id: str
    freeze_id: str
    freeze_digest: str
    cutoff_policy_digest: str
    cutoff_at_utc: str
    profile_digest: str
    decision_policy_digest: str
    decision_policy_artifact_digest: str
    engine_contract_digest: str
    engine_version: str
    witness_profile_digest: str

    def to_bytes(self) -> bytes:
        return canonical(asdict(self))

    @property
    def digest(self) -> str:
        return digest(self.to_bytes())


def publish(
    store: Store,
    *,
    freeze_id: str,
    policy_digest: str,
    profile_digest: str,
    decision_policy: PolicyVersion,
    engine_version: str,
    witness_profile_digest: str,
) -> str:
    from matchvet.candidate_primitives import retain_health
    from matchvet.causal_trust import _PROFILE_DIGEST
    from matchvet.f13 import causal_engine_contract, causal_engine_version_identity
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.t15 import PolicyStatus, PolicyVersion

    artifacts = ArtifactStore(store)
    freeze = MatchweekMembershipRepository(store).get_by_id(freeze_id)
    if freeze is None:
        raise MatchweekResearchError("Exact candidate F06 freeze is missing.")
    cutoffs = MatchEvidenceCutoffRepository(store)
    policy = cutoffs.read_policy(policy_digest)
    boundaries = cutoffs.replay_for_freeze(freeze_id, policy_digest)
    if (
        policy.rule != CORRECTED_RULE
        or policy.lead_time_seconds != 21600
        or not boundaries
        or len({row.cutoff_at_utc for row in boundaries}) != 1
    ):
        raise MatchweekResearchError("Candidate requires exact corrected F07/common T.")
    PreferenceProfileRepository(store).replay(profile_digest)
    checked = PolicyVersion.from_mapping(decision_policy.to_dict())
    if checked.mode is not PolicyStatus.RESEARCH_ONLY or checked.digest != decision_policy.digest:
        raise MatchweekResearchError("Candidate decision policy must be exact RESEARCH_ONLY.")
    if (
        engine_version != causal_engine_version_identity()
        or witness_profile_digest != _PROFILE_DIGEST
    ):
        raise MatchweekResearchError("Unsupported explicit candidate engine or witness profile.")
    artifacts.publish_artifact(
        canonical(freeze_payload(freeze, include_digest=False)),
        FREEZE_MEDIA_TYPE,
        expected_digest=freeze.freeze_digest.removeprefix("sha256:"),
    )
    for reference in freeze.provider_health_references:
        retain_health(store, artifacts, reference.record_digest)
    engine = artifacts.publish_artifact(canonical(causal_engine_contract()), ENGINE_MEDIA_TYPE)
    decision = artifacts.publish_artifact(canonical(checked.to_dict()), POLICY_MEDIA_TYPE)
    candidate = CausalCandidateContract(
        1,
        CAUSAL_CONTRACT,
        _logical_identity(freeze.season, freeze.matchweek_friday),
        freeze_id,
        freeze.freeze_digest.removeprefix("sha256:"),
        policy_digest,
        boundaries[0].cutoff_at_utc,
        profile_digest,
        checked.digest,
        decision.digest,
        engine.digest,
        engine_version,
        witness_profile_digest,
    )
    return artifacts.publish_artifact(candidate.to_bytes(), CANDIDATE_MEDIA_TYPE).digest


def resolve(store: Store, candidate_digest: str) -> CausalCandidateContract:
    from matchvet.candidate_primitives import verify_health
    from matchvet.causal_trust import _PROFILE_DIGEST
    from matchvet.f13 import causal_engine_contract, causal_engine_version_identity
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.t15 import PolicyStatus, PolicyVersion

    require_digest(candidate_digest)
    artifacts = ArtifactStore(store)

    def read(reference: str, media: str) -> bytes:
        require_digest(reference)
        record = artifacts.verify_artifact(reference)
        if (record.media_type, record.retention_class) != (media, "PROTECTED"):
            raise MatchweekResearchError("Missing exact protected candidate dependency.")
        return artifacts.read_artifact(reference)

    try:
        content = read(candidate_digest, CANDIDATE_MEDIA_TYPE)
        value = CausalCandidateContract(**json.loads(content))
        if (
            value.to_bytes() != content
            or type(value.schema_version) is not int
            or (value.schema_version != 1 or value.contract_version != CAUSAL_CONTRACT)
        ):
            raise MatchweekResearchError("Unsupported candidate descriptor contract.")
        freeze = MatchweekMembershipRepository(store).get_by_id(value.freeze_id)
        if freeze is None or (
            freeze.freeze_digest.removeprefix("sha256:"),
            _logical_identity(freeze.season, freeze.matchweek_friday),
        ) != (value.freeze_digest, value.logical_matchweek_id):
            raise MatchweekResearchError("Candidate differs from exact logical Matchweek/F06.")
        if read(value.freeze_digest, FREEZE_MEDIA_TYPE) != canonical(
            freeze_payload(freeze, include_digest=False)
        ):
            raise MatchweekResearchError("Candidate F06 canonical preimage differs.")
        for reference in freeze.provider_health_references:
            verify_health(store, reference.record_digest)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.read_policy(value.cutoff_policy_digest)
        boundaries = cutoffs.replay_for_freeze(value.freeze_id, value.cutoff_policy_digest)
        if (
            policy.rule != CORRECTED_RULE
            or policy.lead_time_seconds != 21600
            or (
                not boundaries or {row.cutoff_at_utc for row in boundaries} != {value.cutoff_at_utc}
            )
        ):
            raise MatchweekResearchError("Candidate differs from exact corrected F07/common T.")
        PreferenceProfileRepository(store).replay(value.profile_digest)
        decision_bytes = read(value.decision_policy_artifact_digest, POLICY_MEDIA_TYPE)
        decision = PolicyVersion.from_mapping(json.loads(decision_bytes))
        if (
            decision.mode is not PolicyStatus.RESEARCH_ONLY
            or decision.digest != value.decision_policy_digest
            or canonical(decision.to_dict()) != decision_bytes
        ):
            raise MatchweekResearchError("Candidate decision policy differs.")
        if (
            read(value.engine_contract_digest, ENGINE_MEDIA_TYPE)
            != canonical(causal_engine_contract())
            or value.engine_version != causal_engine_version_identity()
            or value.witness_profile_digest != _PROFILE_DIGEST
        ):
            raise MatchweekResearchError("Unsupported candidate engine/witness identity.")
        return value
    except MatchweekResearchError:
        raise
    except (ArtifactError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise MatchweekResearchError("Malformed or missing candidate descriptor.") from error


def writer_contract(candidate_digest: str | None, selection_contract: str | None) -> str:
    """Dispatch caller context only; stored reader resolution cannot change this."""
    contract = selection_contract or (
        CAUSAL_CONTRACT if candidate_digest is not None else HISTORICAL_CONTRACT
    )
    if contract not in {CAUSAL_CONTRACT, HISTORICAL_CONTRACT} or (
        contract == HISTORICAL_CONTRACT and candidate_digest is not None
    ):
        raise MatchweekResearchError("Unsupported or mismatched explicit writer contract.")
    if contract == CAUSAL_CONTRACT:
        require_digest(candidate_digest)
    return contract


def require_weather_context(owner: MatchweekResearchRepository, request: WeatherRequest) -> None:
    """Bind direct weather acquisition/health to one exact candidate target."""
    from datetime import datetime

    candidate_digest = owner.candidate_contract_digest
    if candidate_digest is None:
        raise MatchweekResearchError("Explicit weather candidate context is required.")
    candidate = owner.resolve_candidate(candidate_digest)
    rows = MatchEvidenceCutoffRepository(owner._store).replay_for_freeze(
        candidate.freeze_id, candidate.cutoff_policy_digest
    )
    matching = [row for row in rows if row.fixture_id == request.fixture_id]
    if len(matching) != 1 or datetime.fromisoformat(request.cutoff_utc) != datetime.fromisoformat(
        candidate.cutoff_at_utc
    ):
        raise MatchweekResearchError("Weather request differs from explicit candidate context.")
    kickoff = (
        owner._store._connection_for_repository()
        .execute(
            "SELECT kickoff_utc FROM fixture_revisions WHERE revision_id = ? AND fixture_id = ?",
            (matching[0].fixture_revision_ref, request.fixture_id),
        )
        .fetchone()
    )
    if kickoff is None or datetime.fromisoformat(str(kickoff[0])) != request.target_time:
        raise MatchweekResearchError("Weather target differs from the exact candidate revision.")
    owner.require_causal_write(candidate_digest)


def check_occupancy(
    owner: MatchweekResearchRepository, logical: str, candidate_digest: str | None
) -> None:
    """Same cross-version predicate at entry and guarded transactional insertion.

    Raw source rows and descriptors alone have no candidate association. Recognized
    malformed associations refuse rather than disappearing from the scan.
    """
    from matchvet.runs import RunInputContract

    store = owner._store
    if store._artifact_catalog_scope is not None:
        raise MatchweekResearchError("Stored reader context cannot authorize candidate writes.")
    members = MatchweekMembershipRepository(store)
    cutoffs = MatchEvidenceCutoffRepository(store)
    artifacts = ArtifactStore(store)
    freezes: dict[str, str] = {}
    policies: set[str] = set()

    def check(freeze_id: str, policy_digest: str, contract: str | None) -> None:
        key = (freeze_id, policy_digest)
        if key in owner._association_cache:
            freezes[freeze_id] = owner._association_cache[key]
            policies.add(policy_digest)
        if freeze_id not in freezes:
            freeze = members.get_by_id(freeze_id)
            if freeze is None:
                raise MatchweekResearchError("Retained candidate F06 association is missing.")
            freezes[freeze_id] = _logical_identity(freeze.season, freeze.matchweek_friday)
        if policy_digest not in policies:
            cutoffs.read_policy(policy_digest)
            policies.add(policy_digest)
        owner._association_cache[key] = freezes[freeze_id]
        if contract is not None:
            candidate = owner.resolve_candidate(contract)
            if (candidate.freeze_id, candidate.cutoff_policy_digest) != (freeze_id, policy_digest):
                raise MatchweekResearchError("Retained candidate association differs.")
        if freezes[freeze_id] == logical and contract != candidate_digest:
            raise MatchweekResearchError(
                "A conflicting cross-version candidate already occupies this Matchweek."
            )

    try:
        for encoded, stored_digest, matchweek in (
            store._connection_for_repository()
            .execute("SELECT input_contract_json, input_digest, matchweek FROM research_runs")
            .fetchall()
        ):
            run_key = (str(encoded), str(stored_digest), str(matchweek))
            if run_key in owner._run_association_cache:
                check(*owner._run_association_cache[run_key])
                continue
            inputs = RunInputContract.from_stored_json(str(encoded))
            values = inputs.identity_values
            name = values["canonical_contract"]
            if name != "MATCHVET_V2_ANALYZE_MATCHWEEK_V1" and not name.startswith(
                RUN_CONTRACT + ":"
            ):
                if name.startswith("MATCHVET_V2_ANALYZE_MATCHWEEK"):
                    raise MatchweekResearchError("Unsupported retained F15 candidate contract.")
                continue
            if candidate_digest is None and name == "MATCHVET_V2_ANALYZE_MATCHWEEK_V1":
                continue
            if inputs.aggregate_digest != stored_digest:
                raise MatchweekResearchError("Retained F15 candidate identity is invalid.")
            if not values["source"].startswith("F06:") or not values["cutoff"].startswith("F07:"):
                raise MatchweekResearchError("Malformed retained F15 predecessor association.")
            rows = (
                store._connection_for_repository()
                .execute(
                    "SELECT freeze_id FROM v2_matchweek_membership_freezes WHERE freeze_digest = ?",
                    (values["source"].removeprefix("F06:"),),
                )
                .fetchall()
            )
            if len(rows) != 1:
                raise MatchweekResearchError("Ambiguous retained F15 candidate freeze.")
            freeze_id = str(rows[0][0])
            freeze = members.get_by_id(freeze_id)
            assert freeze is not None
            if freeze.matchweek_friday != matchweek:
                raise MatchweekResearchError("Retained F15 logical Matchweek association differs.")
            _, policy_digest, cutoff_list = values["cutoff"].split(":", 2)
            expected_cutoffs = tuple(
                sorted(row.cutoff_id for row in cutoffs.replay_for_freeze(freeze_id, policy_digest))
            )
            if not expected_cutoffs or tuple(cutoff_list.split(",")) != expected_cutoffs:
                raise MatchweekResearchError("Ambiguous retained F15 boundary association.")
            contract = (
                name.removeprefix(RUN_CONTRACT + ":")
                if name.startswith(RUN_CONTRACT + ":")
                else None
            )
            check(freeze_id, policy_digest, contract)
            owner._run_association_cache[run_key] = (freeze_id, policy_digest, contract)
        media_schemas = {
            "application/vnd.matchvet.f11-evidence-set.v3+json": 3,
            "application/vnd.matchvet.f11-evidence-set.v4+json": 4,
            "application/vnd.matchvet.f11-candidate-history.v1+json": 1,
            "application/vnd.matchvet.v2-contextual-attempt.v1+json": 1,
            "application/vnd.matchvet.causal-contextual-attempt.v2+json": 2,
            "application/vnd.matchvet.f13-model-input.v3+json": 3,
            "application/vnd.matchvet.f13-input-binding.v1+json": 3,
            "application/vnd.matchvet.f13-model-result.v2+json": 2,
            "application/vnd.matchvet.f13-model-result.v3+json": 3,
            "application/vnd.matchvet.f14-decision-input.v2+json": 2,
            "application/vnd.matchvet.f14-decision-input.v3+json": 3,
            "application/vnd.matchvet.f14-decision-result.v2+json": 2,
            "application/vnd.matchvet.f14-decision-result.v3+json": 3,
            "application/vnd.matchvet.f16-match-result.v1+json": 1,
            "application/vnd.matchvet.f16-match-result.v2+json": 2,
            "application/vnd.matchvet.f16-processing-manifest.v1+json": 1,
            "application/vnd.matchvet.f16-processing-manifest.v2+json": 2,
            "application/vnd.matchvet.f15-causal-run-identity.v1+json": 1,
        }
        for metadata in store.artifact_catalog():
            if metadata.media_type not in media_schemas:
                if any(
                    metadata.media_type.startswith(prefix)
                    for prefix in (
                        "application/vnd.matchvet.f11-evidence-set.",
                        "application/vnd.matchvet.f11-candidate-history.",
                        "application/vnd.matchvet.v2-contextual-attempt.",
                        "application/vnd.matchvet.causal-contextual-attempt.",
                        "application/vnd.matchvet.f13-model-result.",
                        "application/vnd.matchvet.f13-model-input.",
                        "application/vnd.matchvet.f13-input-binding.",
                        "application/vnd.matchvet.f14-decision-input.",
                        "application/vnd.matchvet.f14-decision-result.",
                        "application/vnd.matchvet.f15-causal-run-identity.",
                        "application/vnd.matchvet.f16-match-result.",
                        "application/vnd.matchvet.f16-processing-manifest.",
                    )
                ):
                    if metadata.media_type == "application/vnd.matchvet.f13-model-input.v2+json":
                        continue  # Historical history-only raw snapshot has no candidate boundary.
                    raise MatchweekResearchError(
                        "Unsupported retained candidate association contract."
                    )
                continue
            historical = metadata.media_type in {
                "application/vnd.matchvet.f11-evidence-set.v3+json",
                "application/vnd.matchvet.v2-contextual-attempt.v1+json",
                "application/vnd.matchvet.f13-model-result.v2+json",
                "application/vnd.matchvet.f14-decision-input.v2+json",
                "application/vnd.matchvet.f14-decision-result.v2+json",
                "application/vnd.matchvet.f16-match-result.v1+json",
                "application/vnd.matchvet.f16-processing-manifest.v1+json",
            }
            if candidate_digest is None and historical:
                continue
            content = artifacts.read_artifact(metadata.digest)
            value = json.loads(content)
            if (
                canonical(value) != content
                or type(value.get("schema_version")) is not int
                or value["schema_version"] != media_schemas[metadata.media_type]
            ):
                raise MatchweekResearchError("Malformed retained candidate schema association.")
            contract = value.get("candidate_contract_digest")
            if historical:
                if "candidate_contract_digest" in value:
                    raise MatchweekResearchError(
                        "Historical candidate cannot be adopted by a copied field."
                    )
            else:
                require_digest(contract)
            if "f13-model-result" in metadata.media_type:
                value = value["inputs"]
                if value.get("candidate_contract_digest") != contract:
                    raise MatchweekResearchError("Ambiguous model candidate association.")
            if "f14-decision-result" in metadata.media_type:
                value = json.loads(artifacts.read_artifact(value["input_bundle_digest"]))
                if value.get("candidate_contract_digest") != contract:
                    raise MatchweekResearchError("Ambiguous decision candidate association.")
            if "cutoff_id" in value:
                cutoff_id = value["cutoff_id"]
                if cutoff_id not in owner._boundary_cache:
                    boundary = cutoffs.replay(cutoff_id)
                    owner._boundary_cache[cutoff_id] = (boundary.freeze_id, boundary.policy_digest)
                freeze_id, policy_digest = owner._boundary_cache[cutoff_id]
                if (
                    ("freeze_id" in value and value["freeze_id"] != freeze_id)
                    or (
                        "policy_digest" in value
                        and "f16-" not in metadata.media_type
                        and value["policy_digest"] != policy_digest
                    )
                    or (
                        "cutoff_policy_digest" in value
                        and value["cutoff_policy_digest"] != policy_digest
                    )
                ):
                    raise MatchweekResearchError("Ambiguous retained cutoff association.")
            else:
                freeze_id = value["freeze_id"]
                policy_digest = (
                    value["policy_digest"]
                    if "f11-" in metadata.media_type
                    else value["cutoff_policy_digest"]
                )
            check(freeze_id, policy_digest, contract)
    except MatchweekResearchError:
        raise
    except (ArtifactError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        raise MatchweekResearchError(
            "Malformed or ambiguous retained candidate association."
        ) from error

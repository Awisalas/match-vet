"""Synthetic seven-scope Matchweek and cryptographic authority for #84."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from matchvet.artifacts import ArtifactStore
from matchvet.causal_trust import _FLOORS, _Approval, _AuthenticatedTrust, _TrustBundle
from matchvet.causal_witness import (
    _ECDSA_SHA256,
    _ESS,
    _POLICY,
    _SHA256,
    _TST,
    _der,
    _digest,
    _oid_der,
    _query,
)
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
from matchvet.matchweek_research import MatchweekResearchRepository


@dataclass(frozen=True)
class HistoricalV1:
    selection_digest: str
    completion_digest: str
    f16_digest: str
    frozen_artifacts: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class SuccessorWeek:
    root: Path
    request: AnalyzeMatchweekRequest
    manifest_digest: str
    graph: CausalGraphIdentity
    freeze_digest: str
    included_membership_ids: tuple[str, ...]
    historical_v1: HistoricalV1
    frozen_artifacts: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class CausalGraphIdentity:
    logical_id: str
    cutoff: str


@dataclass(frozen=True)
class SyntheticAuthority:
    bundle: _TrustBundle
    approval: _Approval
    authenticated: _AuthenticatedTrust
    signer_der: bytes
    anchor_der: bytes
    signer_pem: Path
    anchor_pem: Path
    signer_key: Path


def _run_openssl(*arguments: str) -> None:
    result = subprocess.run(
        ("openssl", *arguments),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Synthetic RFC3161 fixture generation failed.")


def synthetic_authority(root: Path) -> SyntheticAuthority:
    """Create an isolated P-384 timestamp signer without a live trust source."""
    root.mkdir(parents=True, exist_ok=True)
    root_key = root / "root.key"
    signer_key = root / "signer.key"
    root_pem = root / "root.pem"
    signer_pem = root / "signer.pem"
    _run_openssl(
        "genpkey",
        "-algorithm",
        "EC",
        "-pkeyopt",
        "ec_paramgen_curve:P-384",
        "-out",
        str(root_key),
    )
    _run_openssl(
        "req",
        "-x509",
        "-new",
        "-key",
        str(root_key),
        "-subj",
        "/CN=MatchVet #84 synthetic root",
        "-set_serial",
        "1",
        "-days",
        "3650",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-out",
        str(root_pem),
    )
    _run_openssl(
        "genpkey",
        "-algorithm",
        "EC",
        "-pkeyopt",
        "ec_paramgen_curve:P-384",
        "-out",
        str(signer_key),
    )
    request = root / "signer.csr"
    _run_openssl(
        "req",
        "-new",
        "-key",
        str(signer_key),
        "-subj",
        "/CN=MatchVet #84 synthetic timestamp signer",
        "-out",
        str(request),
    )
    extension = root / "signer-extensions.cnf"
    extension.write_text(
        "[timestamp_signer]\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,nonRepudiation\n"
        "extendedKeyUsage=critical,timeStamping\n"
        "subjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid,issuer\n",
        encoding="ascii",
    )
    _run_openssl(
        "x509",
        "-req",
        "-in",
        str(request),
        "-CA",
        str(root_pem),
        "-CAkey",
        str(root_key),
        "-CAcreateserial",
        "-days",
        "3650",
        "-extfile",
        str(extension),
        "-extensions",
        "timestamp_signer",
        "-out",
        str(signer_pem),
    )
    signer_der_path = root / "signer.der"
    anchor_der_path = root / "root.der"
    _run_openssl("x509", "-in", str(signer_pem), "-outform", "DER", "-out", str(signer_der_path))
    _run_openssl("x509", "-in", str(root_pem), "-outform", "DER", "-out", str(anchor_der_path))
    signer_der = signer_der_path.read_bytes()
    anchor_der = anchor_der_path.read_bytes()
    retained_wire = Path(__file__).resolve().parents[1] / (
        "docs/research/cb01-sigstore-witness-2026-10-05"
    )
    bundle = _TrustBundle(
        tuple((retained_wire / f"{version}.root.json").read_bytes() for version in range(11, 16)),
        (retained_wire / "timestamp.json").read_bytes(),
        (retained_wire / "snapshot.json").read_bytes(),
        (retained_wire / "targets.json").read_bytes(),
        (retained_wire / "trusted_root.json").read_bytes(),
    )
    approval = _Approval(
        "2020-01-01T00:00:00Z",
        "2099-01-01T00:00:00Z",
        _FLOORS,
        _digest(bundle.trusted_root),
        "issue84-isolated-synthetic-authority",
    )
    authenticated = _AuthenticatedTrust(
        signer_der,
        anchor_der,
        "2020-01-01T00:00:00Z",
        None,
        (),
        _FLOORS,
    )
    return SyntheticAuthority(
        bundle,
        approval,
        authenticated,
        signer_der,
        anchor_der,
        signer_pem,
        root_pem,
        signer_key,
    )


def install_synthetic_authority(
    monkeypatch: pytest.MonkeyPatch, authority: SyntheticAuthority
) -> None:
    """Replace only test trust activation and its pinned chain asset lookup."""
    from matchvet.causal_selection import _WitnessAttempt

    monkeypatch.setattr(
        "matchvet.causal_selection._load_approval",
        lambda _store: (authority.approval, authority.bundle),
    )
    monkeypatch.setattr(
        "matchvet.causal_trust._authenticate",
        lambda _bundle: authority.authenticated,
    )
    original_read_bytes = Path.read_bytes
    module_root = Path(__file__).resolve().parents[1] / "src/matchvet/data/cb01"
    replacements = {
        module_root / "sigstore-tsa-leaf.der": authority.signer_der,
        module_root / "sigstore-tsa-root.der": authority.anchor_der,
    }
    original_evidence = _WitnessAttempt._evidence

    def read_bytes(path: Path) -> bytes:
        replacement = replacements.get(path)
        return replacement if replacement is not None else original_read_bytes(path)

    def synthetic_evidence(attempt: Any, response: bytes, parsed: Any) -> Any:
        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "read_bytes", read_bytes)
            return original_evidence(attempt, response, parsed)

    monkeypatch.setattr(_WitnessAttempt, "_evidence", synthetic_evidence)


def _integer(value: int) -> bytes:
    if value < 0:
        raise ValueError("Synthetic timestamp integers must be positive.")
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if raw[0] & 128:
        raw = b"\0" + raw
    return _der(2, raw)


def synthetic_timestamp_response(
    request: bytes, authority: SyntheticAuthority, gen_time: datetime
) -> bytes:
    """Build a strict RFC3161 token and sign it with the isolated P-384 key."""
    if gen_time.tzinfo is None or gen_time.utcoffset() != timedelta(0):
        raise ValueError("Synthetic genTime must use UTC.")
    gen_time = gen_time.replace(microsecond=0)
    imprint, nonce = _query(request)
    cert_fields = _node(authority.signer_der, 48).children()[0].children()
    algorithm = _der(48, _oid_der(_SHA256) + b"\x05\0")
    tst_info = _der(
        48,
        _integer(1)
        + _oid_der(_POLICY)
        + _der(48, algorithm + _der(4, imprint))
        + _integer(1)
        + _der(24, gen_time.strftime("%Y%m%d%H%M%SZ").encode("ascii"))
        + _der(48, _der(128, b"\x01"))
        + _integer(nonce)
        + _der(160, _der(164, cert_fields[5].raw)),
    )
    ess_cert_id = _der(
        48,
        _der(4, hashlib.sha256(authority.signer_der).digest())
        + _der(48, _der(48, _der(164, cert_fields[3].raw)) + cert_fields[1].raw),
    )
    attributes = (
        _der(48, _oid_der("1.2.840.113549.1.9.3") + _der(49, _oid_der(_TST))),
        _der(
            48,
            _oid_der("1.2.840.113549.1.9.4") + _der(49, _der(4, hashlib.sha256(tst_info).digest())),
        ),
        _der(
            48,
            _oid_der("1.2.840.113549.1.9.5")
            + _der(49, _der(23, gen_time.strftime("%y%m%d%H%M%SZ").encode("ascii"))),
        ),
        _der(48, _oid_der(_ESS) + _der(49, _der(48, _der(48, ess_cert_id)))),
    )
    signed_attributes = tuple(sorted(attributes))
    signed_set = _der(49, b"".join(signed_attributes))
    with tempfile.TemporaryDirectory(prefix="matchvet-issue84-signature-") as directory:
        work = Path(directory)
        signed_set_path = work / "signed-attributes.der"
        signature_path = work / "signature.der"
        signed_set_path.write_bytes(signed_set)
        _run_openssl(
            "dgst",
            "-sha256",
            "-sign",
            str(authority.signer_key),
            "-out",
            str(signature_path),
            str(signed_set_path),
        )
        signature = signature_path.read_bytes()
    signer_info = _der(
        48,
        _integer(1)
        + _der(48, cert_fields[3].raw + cert_fields[1].raw)
        + algorithm
        + _der(160, b"".join(signed_attributes))
        + _der(48, _oid_der(_ECDSA_SHA256))
        + _der(4, signature),
    )
    signed_data = _der(
        48,
        _integer(3)
        + _der(49, algorithm)
        + _der(48, _oid_der(_TST) + _der(160, _der(4, tst_info)))
        + _der(160, authority.signer_der)
        + _der(49, signer_info),
    )
    token = _der(
        48,
        _oid_der("1.2.840.113549.1.7.2") + _der(160, signed_data),
    )
    return _der(48, _der(48, _integer(0)) + token)


def copy_store(source: Path, destination: Path) -> None:
    shutil.copytree(source / "objects", destination / "objects")
    shutil.copyfile(source / "store.sqlite3", destination / "store.sqlite3")


def _next_friday_with_future_cutoff(now: datetime) -> date:
    candidate = now.date() + timedelta(days=(4 - now.weekday()) % 7)
    cutoff = datetime.combine(candidate, time(12), tzinfo=UTC)
    if cutoff <= now + timedelta(hours=24):
        candidate += timedelta(days=7)
    return candidate


def _synthetic_rows(friday: date) -> dict[str, tuple[tuple[str, str, str, str], ...]]:
    from matchvet.ingestion import TARGET_LEAGUES

    # Source rows use each league's local clock. Keep one Friday, one Saturday,
    # and one Monday fixture while all seven F06 scopes remain in the assessment.
    local_schedule = {
        "serie_a": (friday, time(20, 0)),
        "la_liga": (friday + timedelta(days=1), time(20, 0)),
        "premier_league": (friday + timedelta(days=3), time(21, 0)),
    }
    by_key = {league.key: league for league in TARGET_LEAGUES}
    rows: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
    for key, (match_date, match_time) in local_schedule.items():
        league = by_key[key]
        row = (
            match_date.isoformat(),
            match_time.strftime("%H:%M"),
            f"Issue84 {league.name} Home",
            f"Issue84 {league.name} Away",
        )
        rows[key] = (row,)
    rows["belgian_pro_league"] = ()
    return rows


def _node(raw: bytes, tag: int) -> _DERNode:
    value, end = _read_der(raw)
    if end != len(raw) or value.tag != tag:
        raise ValueError("Unexpected synthetic certificate DER.")
    return value


@dataclass(frozen=True)
class _DERNode:
    tag: int
    content: bytes
    raw: bytes

    def children(self) -> tuple[_DERNode, ...]:
        output: list[_DERNode] = []
        offset = 0
        while offset < len(self.content):
            child, offset = _read_der(self.content, offset)
            output.append(child)
        return tuple(output)


def _read_der(raw: bytes, offset: int = 0) -> tuple[_DERNode, int]:
    if offset + 2 > len(raw):
        raise ValueError("Truncated synthetic certificate DER.")
    start = offset
    tag, size = raw[offset], raw[offset + 1]
    offset += 2
    if size & 128:
        width = size & 127
        if not 1 <= width <= 4 or offset + width > len(raw):
            raise ValueError("Unsupported synthetic certificate DER length.")
        size = int.from_bytes(raw[offset : offset + width], "big")
        offset += width
    end = offset + size
    if end > len(raw):
        raise ValueError("Synthetic certificate DER exceeds its parent.")
    return _DERNode(tag, raw[offset:end], raw[start:end]), end


def build_successor_week(root: Path, historical_graph: object) -> SuccessorWeek:
    """Build v1 and causal Matchweeks in one temporary SQLite catalog."""
    from dataclasses import replace

    from matchweek_research_support import Clock
    from test_matchweek_membership import _persistable_schedule_assessment
    from test_matchweek_research import Graph

    from matchvet.candidate_primitives import HEALTH_MEDIA_TYPE
    from matchvet.f10 import V2_REQUIREMENT_CATALOG
    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f12 import CAUSAL_F12_ATTEMPT_MEDIA_TYPE
    from matchvet.f13 import causal_engine_version_identity
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.f15 import AnalyzeMatchweekRequest
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import CORRECTED_RULE
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    if not isinstance(historical_graph, Graph):
        raise TypeError("The integrated proof requires the retained historical F16 graph.")
    copy_store(historical_graph.root, root)
    with open_store(root / "store.sqlite3", private_root=root) as store:
        history = MatchweekResearchRepository(store, clock=Clock()).seal_completed(
            historical_graph.f16
        )
        artifacts = ArtifactStore(store)
        history_selection = artifacts.verify_manifest(history.digest)
        history_receipt = artifacts.verify_manifest(history.completion_receipt_digest)
        history_digests = {
            history.digest,
            history.completion_receipt_digest,
            *(ref.digest for ref in history_selection.artifacts),
            *(ref.digest for ref in history_receipt.artifacts),
        }
        historical_v1 = HistoricalV1(
            history.digest,
            history.completion_receipt_digest,
            historical_graph.f16,
            tuple((digest, artifacts.read_artifact(digest)) for digest in sorted(history_digests)),
        )

        now = datetime.now(UTC)
        friday = _next_friday_with_future_cutoff(now)
        friday_text = friday.isoformat()
        assessment = _persistable_schedule_assessment(
            store,
            root,
            ((friday_text, "20:00", "Issue84 placeholder home", "Issue84 placeholder away"),),
            matchweek_friday=friday_text,
            rows_by_league=_synthetic_rows(friday),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store, clock=lambda: now).freeze_exact(
            "2026-27",
            friday_text,
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy_digest = cutoffs.persist_policy(
            CutoffPolicy("issue84-seven-scope", "1", 21600, rule=CORRECTED_RULE)
        )
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, policy_digest)
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        policy = PolicyVersion(version="issue84-integrated")
        owner = MatchweekResearchRepository(store)
        from matchvet.causal_trust import _PROFILE_DIGEST

        candidate_digest = owner.publish_candidate(
            freeze_id=freeze.freeze_id,
            policy_digest=policy_digest,
            profile_digest=profile.digest,
            decision_policy=policy,
            engine_version=causal_engine_version_identity(),
            witness_profile_digest=_PROFILE_DIGEST,
        )
        request = AnalyzeMatchweekRequest(
            friday_text,
            freeze.freeze_id,
            policy_digest,
            tuple(sorted(boundary.cutoff_id for boundary in boundaries)),
            V2_REQUIREMENT_CATALOG.digest,
            causal_engine_version_identity(),
            profile.digest,
            policy,
            candidate_digest,
        )
        owner = MatchweekResearchRepository(store, candidate_contract_digest=candidate_digest)
        locations: dict[str, VenueLocation] = {}
        weather_responses: dict[str, dict[str, object]] = {}
        freeze_value = MatchweekMembershipRepository(store).get_by_id(freeze.freeze_id)
        assert freeze_value is not None
        members = {member.membership_id: member for member in freeze_value.memberships}
        for boundary in boundaries:
            member = members[boundary.membership_id]
            kickoff = member.controlling_revision.kickoff_utc
            assert kickoff is not None
            venue = VenueLocation(
                "issue84-" + member.fixture_id,
                "Issue84 synthetic stadium",
                6.5,
                3.4,
                "synthetic-fixture",
                "https://venue.test/issue84",
                "2026-09-16T12:00:00Z",
            )
            weather_request = WeatherRequest(
                member.fixture_id,
                kickoff,
                boundary.cutoff_at_utc,
                venue,
            )
            locations[member.fixture_id] = venue
            issue_time = datetime.fromisoformat(boundary.cutoff_at_utc) - timedelta(hours=1)
            weather_responses[weather_request.url] = {
                "latitude": venue.latitude,
                "longitude": venue.longitude,
                "forecast_issue_time": issue_time.isoformat().replace("+00:00", "Z"),
                "hourly": {
                    "time": [weather_request.interval_start_utc],
                    "temperature_2m": [26],
                },
            }
        weather_client = StaticWeatherClient(
            weather_responses,
            retrieved_at_utc="2026-09-16T12:00:00Z",
        )
        evidence = F11EvidenceRepository(store, candidate_contract_digest=candidate_digest).build(
            freeze.freeze_id,
            policy_digest,
            weather_client=weather_client,
            locations=locations,
        )
        assert len(weather_client.calls) == len(boundaries)
        evidence_rows = evidence.to_dict()["matches"]
        assert all(row["contextual_attempt"] is not None for row in evidence_rows)
        progress = AnalyzeMatchweek(store, candidate_contract_digest=candidate_digest).start(
            request
        )
        assert progress.analysis_state == "F16_COMPLETE_AWAITING_F17"
        manifests = [
            item.digest
            for item in store.artifact_catalog()
            if item.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(manifests) == 1
        manifest_digest = manifests[0]
        candidate = owner.resolve_candidate(candidate_digest)
        media_types = {metadata.media_type for metadata in store.artifact_catalog()}
        assert CAUSAL_F12_ATTEMPT_MEDIA_TYPE in media_types
        assert HEALTH_MEDIA_TYPE in media_types
        included_membership_ids = tuple(
            sorted(
                member.membership_id
                for member in freeze_value.memberships
                if member.decision.value == "INCLUDED"
            )
        )
        assert len(freeze_value.scopes) == 7
        assert len(included_membership_ids) == 3
        included_scope_keys = {"serie_a", "la_liga", "premier_league"}
        assert all(
            len([m for m in freeze_value.memberships if m.scope_id == scope.scope_id])
            == (1 if scope.league_key in included_scope_keys else 0)
            for scope in freeze_value.scopes
        )
        kickoffs = {
            member.membership_id: datetime.fromisoformat(
                member.controlling_revision.kickoff_utc or ""
            )
            for member in freeze_value.memberships
            if member.decision.value == "INCLUDED"
        }
        earliest_membership = min(kickoffs, key=kickoffs.__getitem__)
        assert members[earliest_membership].scope_id.startswith("serie_a:")
        earliest_kickoff = members[earliest_membership].controlling_revision.kickoff_utc
        assert earliest_kickoff is not None and friday_text in earliest_kickoff
        assert max(kickoffs.values()).date() == friday + timedelta(days=3)
        assert (
            len({cutoffs.replay(boundary.cutoff_id).cutoff_at_utc for boundary in boundaries}) == 1
        )
        expected_cutoff = min(kickoffs.values()) - timedelta(seconds=21600)
        actual_cutoff = datetime.fromisoformat(candidate.cutoff_at_utc)
        assert expected_cutoff == actual_cutoff
        assert actual_cutoff > now + timedelta(minutes=30)
        f16_manifest = artifacts.read_artifact(manifest_digest)
        assert f16_manifest
        _ = replace(request, candidate_contract_digest=candidate_digest)
        frozen_artifacts = tuple(
            (metadata.digest, artifacts.read_artifact(metadata.digest))
            for metadata in store.artifact_catalog()
        )
        return SuccessorWeek(
            root,
            request,
            manifest_digest,
            CausalGraphIdentity(candidate.logical_matchweek_id, candidate.cutoff_at_utc),
            freeze.freeze_digest,
            included_membership_ids,
            historical_v1,
            frozen_artifacts,
        )


def reopen_successor_week(root: Path) -> SuccessorWeek:
    """Reconstruct a test descriptor from an already computed isolated store."""
    from matchvet.artifacts import ManifestVersion
    from matchvet.candidate_primitives import HEALTH_MEDIA_TYPE
    from matchvet.causal_candidate import CANDIDATE_MEDIA_TYPE
    from matchvet.f10 import V2_REQUIREMENT_CATALOG
    from matchvet.f12 import CAUSAL_F12_ATTEMPT_MEDIA_TYPE
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
    from matchvet.f16 import MANIFEST_MEDIA_TYPE as F16_MEDIA_TYPE
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import MatchweekResearchRepository, _version
    from matchvet.research_identity import completion_slot, selection_slot
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion

    with open_store(root / "store.sqlite3", private_root=root) as store:
        artifacts = ArtifactStore(store)
        catalog = store.artifact_catalog()
        candidate_rows = [row for row in catalog if row.media_type == CANDIDATE_MEDIA_TYPE]
        manifest_rows = [row for row in catalog if row.media_type == CAUSAL_MANIFEST_MEDIA_TYPE]
        if len(candidate_rows) != 1 or len(manifest_rows) != 1:
            raise ValueError("The isolated reuse store must contain one exact candidate graph.")
        owner = MatchweekResearchRepository(store)
        candidate = owner.resolve_candidate(candidate_rows[0].digest)
        freeze = MatchweekMembershipRepository(store).get_by_id(candidate.freeze_id)
        if freeze is None:
            raise ValueError("The isolated reuse store is missing its exact F06 freeze.")

        expected_selection_version = ManifestVersion.from_identity(_version("selection"))
        historical_selections = []
        for digest in store.snapshot_manifest_digests():
            manifest = artifacts.verify_manifest(digest)
            if manifest.versions == (expected_selection_version,):
                historical_selections.append(manifest)
        if len(historical_selections) != 1:
            raise ValueError("The isolated reuse store must contain one historical v1 selection.")
        historical_selection = historical_selections[0]
        historical_f16_refs = [
            ref for ref in historical_selection.artifacts if ref.media_type == F16_MEDIA_TYPE
        ]
        if len(historical_f16_refs) != 1:
            raise ValueError("The historical v1 selection must identify one exact F16 manifest.")
        historical_logical_id = historical_selection.matchweek_id.value
        if (
            store.snapshot_manifest_digest_for_snapshot(selection_slot(historical_logical_id))
            != historical_selection.digest
        ):
            raise ValueError("The historical v1 selection is not its exact indexed winner.")
        historical_receipt_digest = store.snapshot_manifest_digest_for_snapshot(
            completion_slot(historical_logical_id)
        )
        if historical_receipt_digest is None:
            raise ValueError("The historical v1 selection is missing its exact receipt.")
        historical_receipt = artifacts.verify_manifest(historical_receipt_digest)
        cutoffs = MatchEvidenceCutoffRepository(store).replay_for_freeze(
            candidate.freeze_id, candidate.cutoff_policy_digest
        )
        policy_value = json.loads(
            artifacts.read_artifact(candidate.decision_policy_artifact_digest)
        )
        request = AnalyzeMatchweekRequest(
            freeze.matchweek_friday,
            candidate.freeze_id,
            candidate.cutoff_policy_digest,
            tuple(sorted(item.cutoff_id for item in cutoffs)),
            V2_REQUIREMENT_CATALOG.digest,
            candidate.engine_version,
            candidate.profile_digest,
            PolicyVersion.from_mapping(policy_value),
            candidate.digest,
        )
        history_digests = {
            historical_selection.digest,
            historical_receipt_digest,
            *(ref.digest for ref in historical_selection.artifacts),
            *(ref.digest for ref in historical_receipt.artifacts),
        }
        historical_v1 = HistoricalV1(
            historical_selection.digest,
            historical_receipt_digest,
            historical_f16_refs[0].digest,
            tuple((digest, artifacts.read_artifact(digest)) for digest in sorted(history_digests)),
        )
        included = tuple(
            sorted(
                member.membership_id
                for member in freeze.memberships
                if member.decision.value == "INCLUDED"
            )
        )
        media_types = {row.media_type for row in catalog}
        if CAUSAL_F12_ATTEMPT_MEDIA_TYPE not in media_types or HEALTH_MEDIA_TYPE not in media_types:
            raise ValueError("The cached successor store is missing F11/F12/F09 evidence.")
        return SuccessorWeek(
            root,
            request,
            manifest_rows[0].digest,
            CausalGraphIdentity(candidate.logical_matchweek_id, candidate.cutoff_at_utc),
            freeze.freeze_digest,
            included,
            historical_v1,
            tuple((row.digest, artifacts.read_artifact(row.digest)) for row in catalog),
        )

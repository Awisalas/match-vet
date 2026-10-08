"""Private selection-v2 orchestration; real successor stage admission remains closed.

Trusted code/kernel, honest WAL/FULL/fsync/locking and one authoritative catalog
history establish local causality. Neither signatures nor this code attest execution
against a hostile catalog owner or restore of an obsolete backup.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Never, Self

from matchvet.artifacts import (
    ArtifactError,
    ArtifactStore,
    ManifestArtifact,
    ManifestVersion,
    SnapshotManifest,
)
from matchvet.causal_trust import _PROFILE, _PROFILE_DIGEST, _Approval, _openssl, _TrustBundle
from matchvet.causal_witness import WitnessError, _canonical, _digest, _ParsedEvent, _request
from matchvet.matchweek_research import (
    FrozenMatchweekResearch,
    MatchweekResearchError,
    MatchweekResearchRepository,
    _Graph,
    _identifier,
    _reference,
)
from matchvet.research_identity import completion_slot, selection_slot
from matchvet.store import Store, VersionIdentity

if TYPE_CHECKING:
    from matchvet.store import _ResearchOperation

_PROVENANCE = "application/vnd.matchvet.causal-selection-witness.v1+json"
_EVIDENCE = "application/vnd.matchvet.causal-selection-evidence.v1+octet-stream"
_PURPOSE = "matchvet-pre-T-selection-witness"


def _version_v2(role: str) -> VersionIdentity:
    name = f"matchvet:matchweek-research-{role}:matchvet-causal-selection-v2"
    return VersionIdentity(
        _identifier("version", name),
        _identifier("version_definition", f"matchvet:matchweek-research-{role}"),
        f"matchweek_research_{role}",
        name,
        _digest(name.encode()),
        2,
    )


@dataclass(frozen=True)
class _CausalGraph(_Graph):
    candidate_digest: str
    freeze_digest: str
    profile_digest: str
    model_digest: str
    engine_digest: str
    decision_policy_digest: str

    def binding_fields(self, selection_digest: str) -> dict[str, str | int]:
        return {
            "purpose": _PURPOSE,
            "schema_version": 2,
            "logical_matchweek_id": self.logical_id,
            "selection_slot_id": selection_slot(self.logical_id),
            "selection_digest": selection_digest,
            "f16_digest": self.f16_digest,
            "graph_digest": _digest(
                _canonical(
                    [
                        {
                            "digest": r.digest,
                            "artifact_id": r.artifact_id.value,
                            "media_type": r.media_type,
                            "byte_length": r.byte_length,
                        }
                        for r in self.references
                    ]
                )
            ),
            "freeze_digest": self.freeze_digest,
            "cutoff_policy_digest": self.policy_digest,
            "cutoff_at_utc": self.cutoff,
            "candidate_contract_digest": self.candidate_digest,
            "witness_profile_digest": _PROFILE_DIGEST,
        }

    def check(self, artifacts: ArtifactStore) -> None:
        digests = tuple(ref.digest for ref in self.references)
        if digests != tuple(sorted(set(digests))) or not {
            self.f16_digest,
            self.candidate_digest,
            self.freeze_digest,
            self.policy_digest,
            self.profile_digest,
            self.model_digest,
            self.engine_digest,
            self.decision_policy_digest,
        }.issubset(digests):
            raise MatchweekResearchError(
                "Causal successor graph lacks its exact complete identity closure."
            )
        for reference in self.references:
            if reference != _reference(artifacts, reference.digest):
                raise MatchweekResearchError("Causal successor graph reference mismatch.")


def _manifest_v2(
    repository: MatchweekResearchRepository,
    graph: _CausalGraph,
    *,
    role: str,
    created: str,
    references: tuple[ManifestArtifact, ...] | None = None,
) -> SnapshotManifest:
    from dataclasses import replace

    version = _version_v2(role)
    # Reuse representation only. All historical v1 bytes/meanings stay unchanged.
    base = repository._manifest(graph, role=role, created=created)
    return replace(
        base,
        versions=(ManifestVersion.from_identity(version),),
        version_manifest_id=_identifier("version_manifest", version.identifier.value),
        artifacts=graph.references if references is None else references,
    )


def _load_approval(store: Store) -> tuple[_Approval, _TrustBundle]:
    # Activation is an authenticated trusted-configuration boundary. No discovery
    # of caller-published artifacts can approve an authority. #81 tests inject this
    # private seam with isolated approval; production stays refusing.
    raise MatchweekResearchError("Authenticated causal profile activation is unavailable.")


def _software() -> tuple[tuple[str, bytes], ...]:
    files = (
        "causal_selection.py",
        "causal_witness.py",
        "causal_trust.py",
        "causal_transport.py",
        "store.py",
        "artifacts.py",
        "research_identity.py",
        "matchweek_research.py",
    )
    sources = tuple(
        ("software-" + name, Path(__file__).with_name(name).read_bytes()) for name in files
    )
    runtime = _canonical(
        {
            "python": sys.version,
            "openssl": _openssl(["version"]).stdout.decode("ascii").strip(),
            "semantics": "matchvet-causal-selection-v2",
        }
    )
    return (*sources, ("software-runtime", runtime))


@dataclass(frozen=True)
class _VerifiedSelectionEvent:
    binding: bytes
    request: bytes
    response: bytes
    profile_digest: str
    lower: str
    upper: str
    evidence: tuple[tuple[str, bytes], ...]

    def provenance(self) -> bytes:
        entries = {name: _digest(raw) for name, raw in self.evidence}
        return _canonical(
            {
                "schema_version": 1,
                "purpose": _PURPOSE,
                "lower_bound_utc": self.lower,
                "upper_bound_utc": self.upper,
                "profile_digest": self.profile_digest,
                "evidence": entries,
                "assurance": "HISTORICAL_RETAINED_TRUST_ONLY",
                "current_revocation_checked": False,
            }
        )

    @property
    def digests(self) -> tuple[str, ...]:
        return tuple(sorted({_digest(raw) for _, raw in self.evidence}))


class _WitnessAttempt:
    """Identity-checked lexical authority, never a reconstructable wire capability."""

    def __init__(
        self,
        operation: _ResearchOperation,
        graph: _CausalGraph,
        approval: _Approval,
        bundle: _TrustBundle,
    ) -> None:
        self._operation = operation
        self._graph = graph
        self._approval = approval
        self._bundle = bundle
        self._sent = False
        self._transport_started = False
        self._event: _VerifiedSelectionEvent | None = None
        fields = graph.binding_fields(operation._selection_digest or "")
        fields["postcommit_entropy"] = secrets.token_bytes(32).hex()
        nonce = int.from_bytes(secrets.token_bytes(32), "big") | (1 << 256)
        fields["nonce"] = str(nonce)
        self._binding = _canonical(fields)
        self._nonce = nonce
        self._request = _request(self._binding, nonce)

    def __copy__(self) -> Self:
        raise TypeError("Witness authority cannot be copied.")

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        raise TypeError("Witness authority cannot be copied.")

    def __reduce__(self) -> Never:
        raise TypeError("Witness authority cannot be serialized.")

    def _check(self) -> None:
        self._operation._check()
        if (
            self._operation._attempt is not self
            or self._operation._phase != "witness_attempt"
            or self._operation._busy
        ):
            raise RuntimeError("Witness attempt is not the original live operation attempt.")

    def _obtain(self) -> _VerifiedSelectionEvent:
        from matchvet.causal_witness import _post, _verify_event

        self._check()
        if self._sent:
            raise RuntimeError("The sole witness transport attempt is consumed.")
        self._sent = True  # Before transport or any callback; timeout is terminal.
        self._operation._busy = True
        try:
            response = _post(self)
            parsed = _verify_event(
                self._request,
                response,
                hashlib.sha256(self._binding).digest(),
                self._nonce,
                self._bundle,
                self._approval,
            )
            event = self._evidence(response, parsed)
        finally:
            self._operation._busy = False
        self._check()
        self._event = event
        return event

    def _check_transport(self) -> None:
        from matchvet.store import Store, _ResearchOperation

        if (
            type(self._operation) is not _ResearchOperation
            or type(self._operation._store) is not Store
        ):
            raise RuntimeError("Transport requires the original concrete operation and Store.")
        _ResearchOperation._check(self._operation)
        if (
            self._operation._attempt is not self
            or self._operation._phase != "witness_attempt"
            or not self._sent
            or not self._operation._busy
        ):
            raise RuntimeError("Transport authority has expired or belongs to another operation.")

    def _start_transport(self) -> bytes:
        _WitnessAttempt._check_transport(self)
        if (
            self._operation._attempt is not self
            or self._operation._phase != "witness_attempt"
            or not self._sent
            or not self._operation._busy
            or self._transport_started
        ):
            raise RuntimeError("Transport requires the original sole live witness attempt.")
        self._transport_started = True
        return self._request

    def _evidence(self, response: bytes, parsed: _ParsedEvent) -> _VerifiedSelectionEvent:
        if parsed.imprint != hashlib.sha256(self._binding).digest() or parsed.nonce != self._nonce:
            raise WitnessError("Verified event differs from the exact request.")
        evidence = (
            ("binding", self._binding),
            ("request", self._request),
            ("response", response),
            ("profile", _PROFILE),
            ("approval", self._approval.evidence()),
            *self._bundle.evidence(),
            (
                "signer",
                Path(__file__)
                .with_name("data")
                .joinpath("cb01/sigstore-tsa-leaf.der")
                .read_bytes(),
            ),
            (
                "anchor",
                Path(__file__)
                .with_name("data")
                .joinpath("cb01/sigstore-tsa-root.der")
                .read_bytes(),
            ),
            *_software(),
        )
        return _VerifiedSelectionEvent(
            self._binding,
            self._request,
            response,
            _PROFILE_DIGEST,
            parsed.lower,
            parsed.upper,
            evidence,
        )


def _evidence_media(name: str) -> str:
    # Physical TUF bytes share their established immutable storage identity.
    # Causal meaning belongs to the profile/binding/provenance, not a relabel.
    if name == "bootstrap" or name.startswith("root-"):
        return "application/vnd.matchvet.sigstore-tuf-root.v1+json"
    return {
        "timestamp": "application/vnd.matchvet.sigstore-tuf-timestamp.v1+json",
        "snapshot": "application/vnd.matchvet.sigstore-tuf-snapshot.v1+json",
        "targets": "application/vnd.matchvet.sigstore-tuf-targets.v1+json",
        "trusted-root": "application/vnd.matchvet.sigstore-trusted-root.v1+json",
    }.get(name, _EVIDENCE)


def _retain_event(
    artifacts: ArtifactStore, event: _VerifiedSelectionEvent
) -> tuple[ManifestArtifact, ...]:
    entries = {}
    for name, raw in event.evidence:
        record = artifacts.publish_artifact(raw, _evidence_media(name), retention_class="PROTECTED")
        entries[name] = record.digest
    body = event.provenance()
    provenance = artifacts.publish_artifact(body, _PROVENANCE, retention_class="PROTECTED")
    return tuple(
        _reference(artifacts, digest) for digest in sorted({provenance.digest, *entries.values()})
    )


def _seal(repository: MatchweekResearchRepository, digest: str) -> FrozenMatchweekResearch:
    store, artifacts = repository._store, repository._artifacts
    if store._research_owner is not None:
        raise MatchweekResearchError("A selection operation is already active.")
    graph = repository._admit_v2(digest)
    if not isinstance(graph, _CausalGraph):
        raise MatchweekResearchError("Unsupported causal successor graph.")
    graph.check(artifacts)
    existing = store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id))
    if existing is not None:
        selection = artifacts.verify_manifest(existing)
        if selection.versions != (ManifestVersion.from_identity(_version_v2("selection")),):
            raise MatchweekResearchError(
                "An occupied cross-version selection slot cannot be adopted."
            )
        selected = _replay(repository, existing)
        if selected.f16_manifest_digest != digest:
            raise MatchweekResearchError("The existing exact selection wins.")
        return selected
    if store.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id)) is not None:
        raise MatchweekResearchError("An occupied completion slot cannot obtain causal authority.")
    approval, bundle = _load_approval(store)
    from matchvet.causal_trust import _authenticate

    approval.require(_authenticate(bundle), bundle)
    try:
        with store._research_operation(graph.logical_id, lambda: None) as operation:
            operation._configure_causal(graph, approval, bundle)
            with store.transaction() as transaction:
                for role in ("selection", "completion"):
                    version = _version_v2(role)
                    actual = store.version(version.identifier)
                    if actual is None:
                        transaction.add_version(version)
                    elif ManifestVersion.from_identity(actual) != ManifestVersion.from_identity(
                        version
                    ):
                        raise MatchweekResearchError("Stored causal protocol version differs.")
            selection = _manifest_v2(
                repository,
                graph,
                role="selection",
                created=datetime.now(UTC).isoformat(timespec="microseconds"),
            )
            record = artifacts._publish_research_manifest(selection, operation, role="selection")
            attempt = operation._begin_witness(graph, approval)
            event = attempt._obtain()
            operation._accept_witness(attempt, event)
            # Consume receipt authority before the first evidence staging/publication.
            operation._start("receipt")
            evidence_refs = _retain_event(artifacts, event)
            refs = tuple(
                sorted(
                    (_reference(artifacts, record.digest), *evidence_refs), key=lambda r: r.digest
                )
            )
            receipt = _manifest_v2(
                repository,
                graph,
                role="completion",
                created=operation._upper_bound or "",
                references=refs,
            )
            try:
                artifacts._publish_manifest(receipt, operation=operation)
            except Exception:
                # Read-only exact indexed validation only. No second staging or publication.
                recovered = _replay(repository, record.digest)
                if recovered.completion_receipt_digest != operation._expected_digest:
                    raise MatchweekResearchError(
                        "Ambiguous commit did not index the exact attempted receipt."
                    ) from None
                return recovered
            return _replay(repository, record.digest)
    except (ArtifactError, RuntimeError, ValueError, OSError) as error:
        if isinstance(error, MatchweekResearchError):
            raise
        raise MatchweekResearchError("Causal selection remains permanently unqualified.") from error


def _replay(
    repository: MatchweekResearchRepository, digest: str, *, qualify: bool = True
) -> FrozenMatchweekResearch:
    try:
        return _replay_checked(repository, digest, qualify=qualify)
    except (ArtifactError, ValueError, KeyError, TypeError, IndexError, OSError) as error:
        if isinstance(error, MatchweekResearchError):
            raise
        raise MatchweekResearchError(
            "Indexed causal selection/receipt failed exact offline replay."
        ) from error


def _replay_checked(
    repository: MatchweekResearchRepository, digest: str, *, qualify: bool = True
) -> FrozenMatchweekResearch:
    store, artifacts = repository._store, repository._artifacts
    selection = artifacts.verify_manifest(digest)
    if selection.versions != (ManifestVersion.from_identity(_version_v2("selection")),):
        raise MatchweekResearchError("Unsupported causal selection version.")
    logical = selection.matchweek_id.value
    if store.snapshot_manifest_digest_for_snapshot(selection_slot(logical)) != digest:
        raise MatchweekResearchError("Selection is not the exact indexed logical winner.")
    receipt_digest = store.snapshot_manifest_digest_for_snapshot(completion_slot(logical))
    if receipt_digest is None:
        raise MatchweekResearchError(
            "Selection without indexed receipt is permanently unqualified."
        )
    receipt = artifacts.verify_manifest(receipt_digest)
    provenance_refs = [ref for ref in receipt.artifacts if ref.media_type == _PROVENANCE]
    if len(provenance_refs) != 1:
        raise MatchweekResearchError("Receipt requires exactly one witness provenance.")
    provenance = json.loads(artifacts.read_artifact(provenance_refs[0].digest))
    binding = json.loads(artifacts.read_artifact(provenance["evidence"]["binding"]))
    # No root guessing or mutable catalog discovery. This indexed receipt names
    # one exact F16; admission must prove equality to the whole selected closure.
    with store._scope_artifact_catalog(frozenset(ref.digest for ref in selection.artifacts)):
        graph = repository._admit_v2(binding["f16_digest"], references=selection.artifacts)
        graph.check(artifacts)
    repository._validate_manifest(
        selection,
        _manifest_v2(repository, graph, role="selection", created=selection.created_at_utc),
    )
    receipt = artifacts.verify_manifest(receipt_digest)
    expected = _manifest_v2(
        repository,
        graph,
        role="completion",
        created=receipt.created_at_utc,
        references=receipt.artifacts,
    )
    repository._validate_manifest(receipt, expected)
    _verify_receipt(repository, graph, digest, receipt, qualify=qualify)
    return FrozenMatchweekResearch(
        digest,
        graph.season,
        graph.friday,
        graph.freeze_id,
        graph.policy_digest,
        graph.cutoff,
        graph.f16_digest,
        receipt_digest,
    )


def _verify_receipt(
    repository: MatchweekResearchRepository,
    graph: _CausalGraph,
    selection: str,
    receipt: SnapshotManifest,
    *,
    qualify: bool,
) -> None:
    from matchvet.causal_witness import _verify_event

    artifacts = repository._artifacts
    provenance_refs = [ref for ref in receipt.artifacts if ref.media_type == _PROVENANCE]
    if len(provenance_refs) != 1:
        raise MatchweekResearchError("Receipt requires exactly one witness provenance.")
    raw = artifacts.read_artifact(provenance_refs[0].digest)
    value = json.loads(raw)
    if (
        _canonical(value) != raw
        or set(value)
        != {
            "schema_version",
            "purpose",
            "lower_bound_utc",
            "upper_bound_utc",
            "profile_digest",
            "evidence",
            "assurance",
            "current_revocation_checked",
        }
        or value["schema_version"] != 1
        or value["purpose"] != _PURPOSE
        or value["profile_digest"] != _PROFILE_DIGEST
        or value["assurance"] != "HISTORICAL_RETAINED_TRUST_ONLY"
        or value["current_revocation_checked"] is not False
    ):
        raise MatchweekResearchError("Unsupported witness provenance.")
    entries = value["evidence"]
    expected_digests = {selection, provenance_refs[0].digest, *entries.values()}
    if tuple(ref.digest for ref in receipt.artifacts) != tuple(sorted(expected_digests)):
        raise MatchweekResearchError("Receipt does not contain its exact full evidence closure.")
    for name, evidence_digest in entries.items():
        record = artifacts.verify_artifact(evidence_digest)
        if record.media_type != _evidence_media(name) or record.retention_class != "PROTECTED":
            raise MatchweekResearchError(
                "Witness evidence media/retention differs from its exact role."
            )
    evidence = {name: artifacts.read_artifact(digest) for name, digest in entries.items()}
    roots = [name for name in evidence if name.startswith("root-")]
    root_names = [f"root-{number}" for number in range(11, 11 + len(roots))]
    software_names = {name for name, _ in _software()}
    required = {
        "binding",
        "request",
        "response",
        "profile",
        "approval",
        "bootstrap",
        "timestamp",
        "snapshot",
        "targets",
        "trusted-root",
        "signer",
        "anchor",
        *root_names,
        *software_names,
    }
    if set(evidence) != required or evidence["profile"] != _PROFILE:
        raise MatchweekResearchError("Missing or unapproved provenance evidence.")
    binding = json.loads(evidence["binding"])
    if (
        _canonical(binding) != evidence["binding"]
        or set(binding) != {*graph.binding_fields(selection), "nonce", "postcommit_entropy"}
        or any(binding[k] != v for k, v in graph.binding_fields(selection).items())
    ):
        raise MatchweekResearchError("Witness binding differs from exact winner/graph/profile.")
    nonce = int(binding["nonce"])
    if (
        str(nonce) != binding["nonce"]
        or nonce.bit_length() < 256
        or len(bytes.fromhex(binding["postcommit_entropy"])) != 32
        or binding["postcommit_entropy"] != bytes.fromhex(binding["postcommit_entropy"]).hex()
    ):
        raise MatchweekResearchError("Witness binding has invalid postcommit entropy/nonce.")
    if evidence["request"] != _request(evidence["binding"], nonce):
        raise MatchweekResearchError("Witness query is not the exact canonical bound request.")
    bundle = _TrustBundle(
        tuple(evidence[name] for name in root_names),
        evidence["timestamp"],
        evidence["snapshot"],
        evidence["targets"],
        evidence["trusted-root"],
    )
    current, current_bundle = _load_approval(repository._store)
    # Exact original approved activation is retained, while current authenticated
    # configuration may raise floors or withdraw trust. It cannot rewrite history.
    prior = json.loads(evidence["approval"])
    original = _Approval(
        prior["not_before"],
        prior["not_after"],
        tuple(tuple(v) for v in prior["floors"]),
        prior["target_digest"],
        prior["history_identity"],
        prior["withdrawn_from"],
        prior["timescale"],
        prior["operator_compliance"],
        prior["profile_digest"],
    )
    if (
        original.evidence() != evidence["approval"]
        or original.history_identity != current.history_identity
    ):
        raise MatchweekResearchError("Uncertain restore or activation history.")
    from matchvet.causal_trust import _asset, _authenticate, _utc

    current.require(_authenticate(current_bundle), current_bundle)
    trust = _authenticate(bundle)
    if (
        evidence["bootstrap"] != _asset("sigstore-root10.json")
        or evidence["signer"] != trust.signer
        or evidence["anchor"] != trust.anchor
    ):
        raise MatchweekResearchError("Exact retained chain/bootstrap differs.")
    event = _verify_event(
        evidence["request"],
        evidence["response"],
        hashlib.sha256(evidence["binding"]).digest(),
        nonce,
        bundle,
        original,
        qualify=qualify,
    )
    if (event.lower, event.upper) != (value["lower_bound_utc"], value["upper_bound_utc"]) or _utc(
        event.upper
    ) >= _utc(graph.cutoff):
        raise MatchweekResearchError("Witness upper bound is not strictly before common T.")
    # Floors constrain new trust admission, not rewrite old historical evidence.
    # Present withdrawal still invalidates qualification of an earlier receipt.
    if (
        qualify
        and current.withdrawn_from is not None
        and _utc(event.upper) >= _utc(current.withdrawn_from)
    ):
        raise MatchweekResearchError("Authenticated withdrawal invalidates present qualification.")

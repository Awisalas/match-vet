"""Retained offline TUF authentication for the causal profile, independent of CB01."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from matchvet.causal_witness import _ENDPOINT, WitnessError, _canonical, _digest

MAX_TUF_ROLE_KEYIDS = 16
MAX_TUF_ROLE_SIGNATURES = 64
OPENSSL_STEP_TIMEOUT_SECONDS = 8

_BOOTSTRAP = "836bff947925edfc23eb9ce17af66fb1e43bb5e2bdd240520985ae52b585eae9"
_SIGNER = "85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7"
_ANCHOR = "2aca8fea5d3ce48b01cc77076293c280e6c23ffe44034757ee7833ca9f45d633"
_TARGET = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66"
_FLOORS = (
    ("root", 15, "73747011d0857ada15479a16c4cae0f3ed03aac698b523b97e1de314ac9d9ca8"),
    ("timestamp", 799, "b8cd928494ed0736a71f93bf0bcb0e1d5bcfc4b871bc564b235306dac513b783"),
    ("snapshot", 165, "8f784ab614ec62bfdd5f568eb2a2e3011668449ba235ed4eb7befa99f8469933"),
    ("targets", 14, "6a697f7f8908c8ab26c11786ecb490b54acec97fa8c802e399f065f8a0cc1acd"),
)


def _asset(name: str) -> bytes:
    return (Path(__file__).resolve().parent / "data" / "cb01" / name).read_bytes()


@dataclass(frozen=True)
class _TrustBundle:
    roots: tuple[bytes, ...]
    timestamp: bytes
    snapshot: bytes
    targets: bytes
    trusted_root: bytes

    def evidence(self) -> tuple[tuple[str, bytes], ...]:
        return (
            ("bootstrap", _asset("sigstore-root10.json")),
            *((f"root-{n}", v) for n, v in enumerate(self.roots, 11)),
            ("timestamp", self.timestamp),
            ("snapshot", self.snapshot),
            ("targets", self.targets),
            ("trusted-root", self.trusted_root),
        )


@dataclass(frozen=True)
class _AuthenticatedTrust:
    signer: bytes
    anchor: bytes
    not_before: str
    not_after: str | None
    expiries: tuple[str, ...]
    versions: tuple[tuple[str, int, str], ...]

    def require_interval(self, lower: str, upper: str) -> None:
        lo, hi = _utc(lower), _utc(upper)
        if (
            lo > hi
            or lo < _utc(self.not_before)
            or (self.not_after is not None and hi > _utc(self.not_after))
            or any(hi >= _utc(v) for v in self.expiries)
        ):
            raise WitnessError("The full event interval exceeds retained trust validity/expiry.")
        for cert in (self.signer, self.anchor):
            with tempfile.TemporaryDirectory(prefix="matchvet-causal-validity-") as directory:
                path = Path(directory) / "cert.der"
                path.write_bytes(cert)
                result = _openssl(
                    ["x509", "-inform", "DER", "-in", str(path), "-noout", "-startdate", "-enddate"]
                )
            dates = dict(line.split("=", 1) for line in result.stdout.decode("ascii").splitlines())
            before, after = (
                datetime.strptime(dates[v], "%b %d %H:%M:%S %Y GMT").replace(tzinfo=UTC)
                for v in ("notBefore", "notAfter")
            )
            if lo < before or hi > after:
                raise WitnessError("Full event interval exceeds certificate validity.")


def _utc(value: str) -> datetime:
    if (
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)",
            value,
        )
        is None
    ):
        raise WitnessError("Unsupported UTC bound.")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _authenticate(bundle: _TrustBundle) -> _AuthenticatedTrust:
    try:
        return _authenticate_checked(bundle)
    except (KeyError, TypeError, ValueError, IndexError, OSError) as error:
        if isinstance(error, WitnessError):
            raise
        raise WitnessError("Malformed retained trust closure.") from error


def _authenticate_checked(bundle: _TrustBundle) -> _AuthenticatedTrust:
    bootstrap = _asset("sigstore-root10.json")
    if _digest(bootstrap) != _BOOTSTRAP or not 5 <= len(bundle.roots) <= 64:
        raise WitnessError("Missing authenticated bootstrap/rotations.")
    prior = _parse_json(bootstrap, "bootstrap")
    deadline = time.monotonic() + 120
    for number, raw in enumerate(bundle.roots, 11):
        root = _parse_json(raw, "root")
        if _root_version(root) != number:
            raise WitnessError("Nonsequential TUF root rotation.")
        _verify_role(root, prior, "root", deadline=deadline)
        _verify_role(root, root, "root", deadline=deadline)
        prior = root
    raws = (bundle.roots[-1], bundle.timestamp, bundle.snapshot, bundle.targets)
    docs = (prior, *(_parse_json(v, "metadata") for v in raws[1:]))
    versions = []
    for (role, floor, pinned), raw, doc in zip(_FLOORS, raws, docs, strict=True):
        version = _metadata_version(doc, role)
        if version < floor or (version == floor and _digest(raw) != pinned):
            raise WitnessError(f"TUF {role} floor/identity violation.")
        if role != "root":
            _verify_role(doc, prior, role, deadline=deadline)
        versions.append((role, version, _digest(raw)))
    for parent, child, role, raw in (
        (docs[1], docs[2], "snapshot", bundle.snapshot),
        (docs[2], docs[3], "targets", bundle.targets),
    ):
        if _referenced_version(parent, role + ".json") != _metadata_version(child, role):
            raise WitnessError("TUF referenced metadata version mismatch.")
        _verify_metadata_reference(parent, role + ".json", raw)
    entry = _trusted_root_target_entry(docs[3])
    if len(bundle.trusted_root) != _positive_int(entry.get("length"), "target length") or _digest(
        bundle.trusted_root
    ) != _target_sha256(entry):
        raise WitnessError("TrustedRoot target length/hash mismatch.")
    target = _parse_json_object(bundle.trusted_root, "TrustedRoot")
    if target.get("mediaType") != "application/vnd.dev.sigstore.trustedroot+json;version=0.1":
        raise WitnessError("Unsupported TrustedRoot media type.")
    authorities = target["timestampAuthorities"]
    matches = [v for v in authorities if v.get("uri") == _ENDPOINT]
    if len(matches) != 1:
        raise WitnessError("TrustedRoot requires the exact single approved endpoint.")
    tsa = matches[0]
    chain = tsa["certChain"]["certificates"]
    if len(chain) != 2:
        raise WitnessError("TrustedRoot requires the exact two-certificate chain.")
    signer, anchor = (base64.b64decode(v["rawBytes"], validate=True) for v in chain)
    if (
        _digest(signer) != _SIGNER
        or _digest(anchor) != _ANCHOR
        or signer != _asset("sigstore-tsa-leaf.der")
        or anchor != _asset("sigstore-tsa-root.der")
    ):
        raise WitnessError("Unapproved signer/anchor pins.")
    expiries = tuple(cast(str, doc["signed"]["expires"]) for doc in docs)
    for expiration in expiries:
        _utc(expiration)
    return _AuthenticatedTrust(
        signer,
        anchor,
        tsa["validFor"]["start"],
        tsa["validFor"].get("end"),
        expiries,
        tuple(versions),
    )


def _parse_json(content: bytes, label: str) -> dict[str, Any]:
    value = _parse_json_object(content, label)
    if not isinstance(value.get("signed"), dict):
        raise WitnessError(f"Sigstore {label} is not signed TUF JSON.")
    return value


def _parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_bad_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, WitnessError) as error:
        raise WitnessError(f"Sigstore {label} is malformed JSON.") from error
    if not isinstance(value, dict):
        raise WitnessError(f"Sigstore {label} is not a JSON object.")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WitnessError("Duplicate JSON key in Sigstore TUF metadata.")
        value[key] = item
    return value


def _bad_constant(value: str) -> None:
    raise WitnessError(f"Invalid non-finite TUF JSON number {value}.")


def _root_version(document: dict[str, Any]) -> int:
    signed = document["signed"]
    if signed.get("_type") != "root" or type(signed.get("version")) is not int:
        raise WitnessError("Sigstore root metadata type or version is invalid.")
    return cast(int, signed["version"])


def _metadata_version(document: dict[str, Any], role: str) -> int:
    signed = document["signed"]
    if (
        signed.get("_type") != role
        or type(signed.get("version")) is not int
        or signed["version"] < 1
    ):
        raise WitnessError(f"Sigstore {role} metadata type or version is invalid.")
    return cast(int, signed["version"])


def _referenced_version(document: dict[str, Any], filename: str) -> int:
    try:
        version = document["signed"]["meta"][filename]["version"]
    except (KeyError, TypeError) as error:
        raise WitnessError(f"Sigstore TUF metadata has no reference to {filename}.") from error
    if type(version) is not int or version < 1:
        raise WitnessError(f"Sigstore TUF reference to {filename} has an invalid version.")
    return version


def _verify_metadata_reference(document: dict[str, Any], filename: str, content: bytes) -> None:
    reference = document["signed"]["meta"][filename]
    if "length" in reference and _positive_int(reference["length"], "TUF metadata length") != len(
        content
    ):
        raise WitnessError(f"Sigstore TUF {filename} length does not match its parent metadata.")
    hashes = reference.get("hashes")
    if hashes is not None:
        if not isinstance(hashes, dict) or not isinstance(hashes.get("sha256"), str):
            raise WitnessError(f"Sigstore TUF {filename} hash reference is malformed.")
        if hashlib.sha256(content).hexdigest() != hashes["sha256"]:
            raise WitnessError(f"Sigstore TUF {filename} hash does not match its parent metadata.")


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise WitnessError(f"{label} must be a positive integer.")
    return value


def _target_sha256(entry: dict[str, Any]) -> str:
    hashes = entry.get("hashes")
    if not isinstance(hashes, dict):
        raise WitnessError("Sigstore TrustedRoot target has no SHA-256 digest.")
    digest_value = hashes.get("sha256")
    if not isinstance(digest_value, str):
        raise WitnessError("Sigstore TrustedRoot target has no SHA-256 digest.")
    digest = digest_value
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise WitnessError("Sigstore TrustedRoot target SHA-256 digest is malformed.")
    return digest


def _trusted_root_target_entry(document: dict[str, Any]) -> dict[str, Any]:
    try:
        entry = document["signed"]["targets"]["trusted_root.json"]
    except (KeyError, TypeError) as error:
        raise WitnessError(
            "Authenticated Sigstore TUF metadata has no trusted_root.json target."
        ) from error
    if not isinstance(entry, dict):
        raise WitnessError("Sigstore TrustedRoot target metadata is malformed.")
    return cast(dict[str, Any], entry)


def _verify_role(
    document: dict[str, Any],
    root: dict[str, Any],
    role: str,
    *,
    deadline: float | None = None,
) -> None:
    signed = document.get("signed")
    signatures = document.get("signatures")
    if not isinstance(signed, dict) or not isinstance(signatures, list):
        raise WitnessError("Sigstore TUF metadata signature structure is malformed.")
    policy = root["signed"]["roles"].get(role)
    if not isinstance(policy, dict):
        raise WitnessError(f"Sigstore TUF root has no {role} role.")
    keyids = policy.get("keyids")
    threshold = policy.get("threshold")
    if (
        not isinstance(keyids, list)
        or not keyids
        or len(keyids) > MAX_TUF_ROLE_KEYIDS
        or any(not isinstance(keyid, str) or not keyid for keyid in keyids)
        or len(keyids) != len(set(keyids))
        or type(threshold) is not int
        or threshold < 1
        or threshold > len(keyids)
    ):
        raise WitnessError(f"Sigstore TUF {role} threshold is malformed.")
    if len(signatures) > MAX_TUF_ROLE_SIGNATURES:
        raise WitnessError(f"Sigstore TUF {role} has too many signature records.")
    signed_bytes = _tuf_canonical_bytes(signed)
    valid_keyids: set[str] = set()
    signature_keyids: set[str] = set()
    keys = root["signed"]["keys"]
    for signature in signatures:
        if not isinstance(signature, dict):
            raise WitnessError("Sigstore TUF signature record is malformed.")
        keyid = signature.get("keyid")
        sig = signature.get("sig")
        if not isinstance(keyid, str) or not isinstance(sig, str):
            raise WitnessError("Sigstore TUF signature identity is malformed.")
        if keyid in signature_keyids:
            raise WitnessError("Sigstore TUF metadata has duplicate signatures for one key.")
        signature_keyids.add(keyid)
        if keyid not in keyids:
            continue
        key = keys.get(keyid)
        if (
            not isinstance(key, dict)
            or key.get("keytype") != "ecdsa"
            or key.get("scheme") != "ecdsa-sha2-nistp256"
        ):
            raise WitnessError("Sigstore TUF signature uses an unsupported key type or scheme.")
        public_pem = key["keyval"].get("public")
        if not isinstance(public_pem, str):
            raise WitnessError("Sigstore TUF ECDSA public key is missing.")
        try:
            signature_der = bytes.fromhex(sig)
        except ValueError as error:
            raise WitnessError("Sigstore TUF ECDSA signature is malformed.") from error
        if deadline is not None:
            _check_crypto_deadline(deadline)
        if _verify_ecdsa(public_pem.encode(), signed_bytes, signature_der):
            valid_keyids.add(keyid)
        if deadline is not None:
            _check_crypto_deadline(deadline)
    if len(valid_keyids) < threshold:
        raise WitnessError(f"Sigstore TUF {role} signature threshold was not met.")


def _check_crypto_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise WitnessError("Sigstore TUF cryptographic work exceeded its causal time bound.")


def _verify_ecdsa(public_pem: bytes, message: bytes, signature: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="matchvet-causal-tuf-sig-") as directory:
        work = Path(directory)
        key_path, message_path, signature_path = (
            work / "key.pem",
            work / "signed.json",
            work / "signature.der",
        )
        key_path.write_bytes(public_pem)
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        try:
            completed = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(key_path),
                    "-signature",
                    str(signature_path),
                    str(message_path),
                ],
                capture_output=True,
                timeout=OPENSSL_STEP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WitnessError("Bounded TUF signature verification failed to complete.") from error
        return completed.returncode == 0 and b"Verified OK" in completed.stdout


def _tuf_canonical_bytes(value: object) -> bytes:
    def encode(item: object) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if type(item) is int:
            return str(item)
        if isinstance(item, str):
            return '"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(item, list):
            return "[" + ",".join(encode(value) for value in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise WitnessError("TUF canonical metadata object keys must be strings.")
            fields = (encode(key) + ":" + encode(item[key]) for key in sorted(item))
            return "{" + ",".join(fields) + "}"
        raise WitnessError("TUF canonical JSON forbids floating-point and unsupported values.")

    return encode(value).encode("utf-8")


def _openssl(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["openssl", *arguments],
            capture_output=True,
            timeout=OPENSSL_STEP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WitnessError("Bounded OpenSSL verification failed to complete.") from error
    if completed.returncode != 0:
        # Details can contain ASN.1 and certificate dumps; persist stable reason codes instead.
        raise WitnessError("Bounded OpenSSL verification rejected the input.")
    return completed


_PROFILE = _canonical(
    {
        "profile": "matchvet-sigstore-causal-event-v1",
        "protocol": "matchvet-causal-selection-v2",
        "endpoint": _ENDPOINT,
        "operator": "sigstore.dev",
        "policy_oid": "1.3.6.1.4.1.57264.2",
        "policy_revision": "3a83b1f015affed68763ef73f7729aa478c650e1",
        "policy_sha256": "97a3306df4f0ea5f5f64a938072bb802492b7cf1fca0661b20de0a6c98071bcf",
        "handler_revision": "3593e847b84fa501e2a0729eaea2c6ac982c4ab3",
        "signer": _SIGNER,
        "anchor": _ANCHOR,
        "bootstrap": _BOOTSTRAP,
        "reviewed_metadata_floors": _FLOORS,
        "initial_trusted_root": _TARGET,
        "digest_algorithm": "2.16.840.1.101.3.4.2.1",
        "signature_algorithm": "1.2.840.10045.4.3.2",
        "curve": "P-384",
        "max_accuracy_microseconds": 1000000,
        "timescale": "UNSMEARED_UTC",
        "leap_interpretation": "NO_DAY_CROSSING",
        "operator_key_to_policy_association": "EXPLICIT_APPROVED_MATCHVET_CONFIGURATION",
        "premises": ["OPERATOR_POLICY_COMPLIANCE", "UNCOMPROMISED_AUTHORITY", "UNSMEARED_UTC"],
        "assurance": "HISTORICAL_RETAINED_TRUST_ONLY",
        "current_revocation_checked": False,
    }
)
_PROFILE_DIGEST = _digest(_PROFILE)


@dataclass(frozen=True)
class _Approval:
    """Authenticated state provided only by the trusted configuration owner.

    Constructing/retaining this object does not activate it. Only the private
    independently configured owner loader can supply current runtime authority.
    """

    not_before: str
    not_after: str
    floors: tuple[tuple[str, int, str], ...]
    target_digest: str
    history_identity: str
    withdrawn_from: str | None = None
    timescale: str = "UNSMEARED_UTC"
    operator_compliance: bool = True
    profile_digest: str = _PROFILE_DIGEST
    owner_record: bytes | None = None
    owner_evidence: bytes | None = None

    def evidence(self) -> bytes:
        if self.owner_evidence is not None:
            return self.owner_evidence
        return _canonical(
            {
                "profile_digest": self.profile_digest,
                "not_before": self.not_before,
                "not_after": self.not_after,
                "floors": self.floors,
                "target_digest": self.target_digest,
                "history_identity": self.history_identity,
                "withdrawn_from": self.withdrawn_from,
                "timescale": self.timescale,
                "operator_compliance": self.operator_compliance,
            }
        )

    def require(
        self,
        trust: _AuthenticatedTrust,
        bundle: _TrustBundle,
        lower: str | None = None,
        upper: str | None = None,
        *,
        qualify: bool = True,
    ) -> None:
        if (
            self.profile_digest != _PROFILE_DIGEST
            or not self.history_identity
            or self.timescale != "UNSMEARED_UTC"
            or self.operator_compliance is not True
            or _utc(self.not_before) >= _utc(self.not_after)
            or self.target_digest != _digest(bundle.trusted_root)
        ):
            raise WitnessError("Missing approved profile/activation/authoritative history.")
        if len(self.floors) != 4 or {r for r, _, _ in self.floors} != {r for r, _, _ in _FLOORS}:
            raise WitnessError("Missing authenticated TUF floors.")
        retained = {r: (v, d) for r, v, d in trust.versions}
        initial = {r: (v, d) for r, v, d in _FLOORS}
        for role, minimum, pinned in self.floors:
            version, digest = retained[role]
            frozen, original = initial[role]
            if (
                type(minimum) is not int
                or minimum < frozen
                or (minimum == frozen and pinned != original)
                or version < minimum
                or (version == minimum and digest != pinned)
                or re.fullmatch("[0-9a-f]{64}", pinned) is None
            ):
                raise WitnessError("Authenticated activation TUF floor/rollback violation.")
        if (lower is None) != (upper is None):
            raise WitnessError("Incomplete event interval.")
        if lower is not None and upper is not None:
            if _utc(lower) < _utc(self.not_before) or _utc(upper) > _utc(self.not_after):
                raise WitnessError("Event interval outside approved activation validity.")
            trust.require_interval(lower, upper)
            if (
                qualify
                and self.withdrawn_from is not None
                and _utc(upper) >= _utc(self.withdrawn_from)
            ):
                raise WitnessError("Authenticated compromise/withdrawal invalidates this event.")

"""Private pre-T event verification. This profile trusts unsmeared UTC compliance.

Offline signatures establish historical retained assurance, never current revocation.
No production activation or live trust refresh is supplied by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import TYPE_CHECKING

from matchvet.causal_transport import _post as _post

if TYPE_CHECKING:
    from matchvet.causal_trust import _Approval, _TrustBundle


class WitnessError(ValueError):
    """The exact causal event cannot qualify."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _event_interval(generalized: str, accuracy: dict[int, int] | None) -> tuple[str, str]:
    match = re.fullmatch(r"([0-9]{14})(?:\.([0-9]{1,18}))?Z", generalized)
    if match is None or (match[2] and match[2].endswith("0")):
        raise WitnessError("Unsupported UTC GeneralizedTime or precision.")
    try:
        base = datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError as error:
        raise WitnessError("Unsupported UTC/leap encoding.") from error
    if not accuracy or set(accuracy) - {2, 128, 129}:
        raise WitnessError("Signed Accuracy is missing, empty or unsupported.")
    if any(type(v) is not int or v < 0 for v in accuracy.values()):
        raise WitnessError("Signed Accuracy is negative or unsupported.")
    for tag in (128, 129):
        if tag in accuracy and not 1 <= accuracy[tag] <= 999:
            raise WitnessError("Signed Accuracy fractional component is invalid.")
    radius = accuracy.get(2, 0) * 1_000_000 + accuracy.get(128, 0) * 1000 + accuracy.get(129, 0)
    if not 0 < radius <= 1_000_000:
        raise WitnessError("Signed Accuracy must be positive and at most one second.")
    fraction = Fraction(int(match[2]), 10 ** len(match[2])) if match[2] else Fraction(0)
    center = fraction * 1_000_000
    try:
        lower = base + timedelta(microseconds=(center - radius).__floor__())
        upper = base + timedelta(microseconds=(center + radius).__ceil__())
    except OverflowError as error:
        raise WitnessError("Unsupported signed UTC interval overflow.") from error
    if lower.date() != upper.date():
        raise WitnessError("The witnessed interval crosses a UTC day boundary.")
    return lower.isoformat(timespec="microseconds"), upper.isoformat(timespec="microseconds")


@dataclass(frozen=True)
class _Node:
    tag: int
    content: bytes
    raw: bytes

    def children(self) -> tuple[_Node, ...]:
        values: list[_Node] = []
        offset = 0
        while offset < len(self.content):
            item, offset = _read(self.content, offset)
            values.append(item)
        return tuple(values)


def _read(raw: bytes, offset: int = 0) -> tuple[_Node, int]:
    start = offset
    if offset + 2 > len(raw) or raw[offset] & 31 == 31:
        raise WitnessError("Truncated or unsupported DER tag.")
    tag, size = raw[offset], raw[offset + 1]
    offset += 2
    if size & 128:
        width = size & 127
        if not 1 <= width <= 4 or offset + width > len(raw) or raw[offset] == 0:
            raise WitnessError("Indefinite or nonminimal DER length.")
        size = int.from_bytes(raw[offset : offset + width], "big")
        offset += width
        if size < 128:
            raise WitnessError("Nonminimal DER length.")
    end = offset + size
    if end > len(raw):
        raise WitnessError("DER exceeds its containing object.")
    return _Node(tag, raw[offset:end], raw[start:end]), end


def _node(raw: bytes, tag: int) -> _Node:
    value, end = _read(raw)
    if end != len(raw) or value.tag != tag:
        raise WitnessError("Unexpected DER structure or trailing bytes.")
    return value


def _int(value: _Node, tag: int = 2) -> int:
    raw = value.content
    if (
        value.tag != tag
        or not raw
        or len(raw) > 65
        or (len(raw) > 1 and ((raw[0] == 0 and raw[1] < 128) or (raw[0] == 255 and raw[1] >= 128)))
    ):
        raise WitnessError("Nonminimal or unsupported DER integer.")
    return int.from_bytes(raw, "big", signed=True)


def _oid(value: _Node) -> str:
    if value.tag != 6 or not value.content:
        raise WitnessError("Malformed DER OID.")
    arcs: list[int] = []
    current = 0
    first_byte = True
    for byte in value.content:
        if first_byte and byte == 128:
            raise WitnessError("Nonminimal DER OID.")
        current = current * 128 + (byte & 127)
        if current.bit_length() > 64:
            raise WitnessError("Unsupported DER OID.")
        first_byte = not bool(byte & 128)
        if first_byte:
            arcs.append(current)
            current = 0
    if not first_byte:
        raise WitnessError("Truncated DER OID.")
    first = arcs.pop(0)
    arc = min(first // 40, 2)
    return ".".join(map(str, (arc, first - arc * 40, *arcs)))


def _der(tag: int, raw: bytes) -> bytes:
    size = len(raw)
    encoded = size.to_bytes(max(1, (size.bit_length() + 7) // 8), "big")
    length = bytes([size]) if size < 128 else bytes([128 | len(encoded)]) + encoded
    return bytes([tag]) + length + raw


def _oid_der(oid: str) -> bytes:
    arcs = [int(v) for v in oid.split(".")]
    values = [40 * arcs[0] + arcs[1], *arcs[2:]]
    encoded = bytearray()
    for value in values:
        group = [value & 127]
        value >>= 7
        while value:
            group.append(128 | (value & 127))
            value >>= 7
        encoded.extend(reversed(group))
    return _der(6, bytes(encoded))


_ENDPOINT = "https://timestamp.sigstore.dev/api/v1/timestamp"
_POLICY = "1.3.6.1.4.1.57264.2"
_SHA256 = "2.16.840.1.101.3.4.2.1"
_ECDSA_SHA256 = "1.2.840.10045.4.3.2"
_TST = "1.2.840.113549.1.9.16.1.4"
_ESS = "1.2.840.113549.1.9.16.2.47"


def _algorithm(node: _Node, oid: str, *, null: bool = False) -> None:
    fields = node.children()
    if (
        node.tag != 48
        or not fields
        or _oid(fields[0]) != oid
        or (len(fields) != 1 and not (null and len(fields) == 2 and fields[1].raw == b"\x05\x00"))
    ):
        raise WitnessError("Unapproved algorithm or parameters.")


def _imprint(node: _Node) -> bytes:
    fields = node.children()
    if node.tag != 48 or len(fields) != 2 or fields[1].tag != 4 or len(fields[1].content) != 32:
        raise WitnessError("Malformed SHA-256 messageImprint.")
    _algorithm(fields[0], _SHA256, null=True)
    return fields[1].content


def _request(binding: bytes, nonce: int) -> bytes:
    if nonce <= 0 or nonce.bit_length() < 256:
        raise WitnessError("Request nonce requires at least 256 unpredictable bits.")
    raw = nonce.to_bytes((nonce.bit_length() + 7) // 8, "big")
    if raw[0] >= 128:
        raw = b"\0" + raw
    imprint = _der(
        48, _der(48, _oid_der(_SHA256) + b"\x05\0") + _der(4, hashlib.sha256(binding).digest())
    )
    return _der(48, b"\x02\x01\x01" + imprint + _oid_der(_POLICY) + _der(2, raw) + b"\x01\x01\xff")


def _query(raw: bytes) -> tuple[bytes, int]:
    fields = _node(raw, 48).children()
    if (
        len(fields) != 5
        or _int(fields[0]) != 1
        or _oid(fields[2]) != _POLICY
        or fields[4].raw != b"\x01\x01\xff"
    ):
        raise WitnessError("Unsupported exact RFC3161 request profile.")
    nonce = _int(fields[3])
    if nonce <= 0:
        raise WitnessError("Request nonce must be positive.")
    return _imprint(fields[1]), nonce


@dataclass(frozen=True)
class _ParsedEvent:
    token: bytes
    imprint: bytes
    nonce: int
    lower: str
    upper: str
    gen_time: str


def _parse_response(response: bytes, signer: bytes, anchor: bytes) -> _ParsedEvent:
    try:
        if not response or len(response) > 1_048_576:
            raise WitnessError("Unsupported response size.")
        return _parse_response_checked(response, signer, anchor)
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError) as error:
        if isinstance(error, WitnessError):
            raise
        raise WitnessError("Malformed RFC3161/CMS/ASN.1.") from error


def _parse_response_checked(response: bytes, signer: bytes, anchor: bytes) -> _ParsedEvent:
    fields = _node(response, 48).children()
    if len(fields) != 2 or fields[0].raw != b"\x30\x03\x02\x01\x00":
        raise WitnessError("RFC3161 requires strict granted status 0.")
    info = fields[1].children()
    if (
        fields[1].tag != 48
        or len(info) != 2
        or _oid(info[0]) != "1.2.840.113549.1.7.2"
        or info[1].tag != 160
    ):
        raise WitnessError("Malformed CMS SignedData.")
    cms = _node(info[1].content, 48).children()
    if (
        len(cms) != 5
        or _int(cms[0]) != 3
        or cms[1].tag != 49
        or cms[3].tag != 160
        or cms[4].tag != 49
    ):
        raise WitnessError("Unsupported CMS fields.")
    algorithms = cms[1].children()
    if len(algorithms) != 1:
        raise WitnessError("CMS requires one digest algorithm.")
    _algorithm(algorithms[0], _SHA256, null=True)
    certificates = cms[3].children()
    if len(certificates) != 1 or certificates[0].raw != signer:
        raise WitnessError("CMS requires the exact approved chain.")
    encap = cms[2].children()
    if cms[2].tag != 48 or len(encap) != 2 or _oid(encap[0]) != _TST or encap[1].tag != 160:
        raise WitnessError("CMS content type must be TSTInfo.")
    octet = _node(encap[1].content, 4)
    tst = _node(octet.content, 48).children()
    if (
        len(tst) not in (7, 8, 9)
        or _int(tst[0]) != 1
        or _oid(tst[1]) != _POLICY
        or _int(tst[3]) <= 0
        or tst[4].tag != 24
        or tst[5].tag != 48
    ):
        raise WitnessError("Malformed/unsupported TSTInfo profile.")
    accuracy: dict[int, int] = {}
    last = -1
    for item in tst[5].children():
        order = {2: 0, 128: 1, 129: 2}.get(item.tag, -1)
        if order <= last:
            raise WitnessError("Duplicate, unordered or unsupported Accuracy field.")
        last = order
        accuracy[item.tag] = _int(item, item.tag)
    nonce_index = 6
    if tst[6].tag == 1:
        if tst[6].raw != b"\x01\x01\xff":
            raise WitnessError("Unsupported ordering field.")
        nonce_index = 7
    nonce = _int(tst[nonce_index])
    if nonce <= 0:
        raise WitnessError("Mandatory signed nonce must be positive.")
    generalized = tst[4].content.decode("ascii")
    lower, upper = _event_interval(generalized, accuracy)
    signers = cms[4].children()
    if len(signers) != 1:
        raise WitnessError("CMS requires one signer.")
    si = signers[0].children()
    if (
        signers[0].tag != 48
        or len(si) != 6
        or _int(si[0]) != 1
        or si[1].tag != 48
        or si[3].tag != 160
        or si[5].tag != 4
        or not si[5].content
    ):
        raise WitnessError("Malformed CMS SignerInfo.")
    _algorithm(si[2], _SHA256, null=True)
    _algorithm(si[4], _ECDSA_SHA256)
    signature = _node(si[5].content, 48).children()
    if len(signature) != 2 or any(not 0 < _int(value) < (1 << 384) for value in signature):
        raise WitnessError("Malformed P-384 ECDSA signature DER.")
    # Exact pinned certificate also pins its P-384 SPKI, extensions and validity.
    cert = _node(signer, 48).children()[0].children()
    tail = tst[nonce_index + 1 :]
    if tail and (len(tail) != 1 or tail[0].raw != _der(160, _der(164, cert[5].raw))):
        raise WitnessError("Unapproved TSTInfo TSA name/extensions.")
    sid = si[1].children()
    if len(sid) != 2 or sid[0].raw != cert[3].raw or sid[1].raw != cert[1].raw:
        raise WitnessError("CMS signer identifier differs from approved certificate.")
    attrs: dict[str, _Node] = {}
    encoded_attrs = si[3].children()
    if tuple(n.raw for n in encoded_attrs) != tuple(sorted(n.raw for n in encoded_attrs)):
        raise WitnessError("Noncanonical CMS signed attribute order.")
    for attr in encoded_attrs:
        pair = attr.children()
        if attr.tag != 48 or len(pair) != 2 or pair[1].tag != 49:
            raise WitnessError("Malformed CMS signed attribute.")
        oid = _oid(pair[0])
        if oid in attrs or len(pair[1].children()) != 1:
            raise WitnessError("Duplicate or multiple CMS signed attribute values.")
        attrs[oid] = pair[1].children()[0]
    if set(attrs) != {"1.2.840.113549.1.9.3", "1.2.840.113549.1.9.4", "1.2.840.113549.1.9.5", _ESS}:
        raise WitnessError("Unapproved CMS signed attributes.")
    if _oid(attrs["1.2.840.113549.1.9.3"]) != _TST or attrs["1.2.840.113549.1.9.4"].raw != _der(
        4, hashlib.sha256(octet.content).digest()
    ):
        raise WitnessError("CMS signed content binding mismatch.")
    ess = attrs[_ESS].children()
    if attrs[_ESS].tag != 48 or len(ess) != 1 or ess[0].tag != 48:
        raise WitnessError("Malformed ESSCertIDv2.")
    ids = ess[0].children()
    if len(ids) != 1 or ids[0].tag != 48:
        raise WitnessError("ESS requires one signer certificate binding.")
    binding = ids[0].children()
    if (
        len(binding) != 2
        or binding[0].raw != _der(4, hashlib.sha256(signer).digest())
        or binding[1].raw != _der(48, _der(48, _der(164, cert[3].raw)) + cert[1].raw)
    ):
        raise WitnessError("ESS signer certificate hash mismatch.")
    signing_time = attrs["1.2.840.113549.1.9.5"]
    if signing_time.tag != 23 or re.fullmatch(rb"[0-9]{12}Z", signing_time.content) is None:
        raise WitnessError("Unsupported CMS signingTime.")
    try:
        datetime.strptime(signing_time.content.decode("ascii"), "%y%m%d%H%M%SZ")
    except ValueError as error:
        raise WitnessError("Unsupported CMS signingTime date.") from error
    # Critical timestamp-only EKU in the exact DER, independent of OpenSSL text.
    extensions = cert[-1]
    if extensions.tag != 163:
        raise WitnessError("Signer extensions are missing.")
    eku = [
        n for n in _node(extensions.content, 48).children() if _oid(n.children()[0]) == "2.5.29.37"
    ]
    if len(eku) != 1 or tuple(n.raw for n in eku[0].children()[1:]) != (
        b"\x01\x01\xff",
        _der(4, _der(48, _oid_der("1.3.6.1.5.5.7.3.8"))),
    ):
        raise WitnessError("Signer EKU must be critical and timestamp-only.")
    return _ParsedEvent(fields[1].raw, _imprint(tst[2]), nonce, lower, upper, generalized)


def _verify_event(
    request: bytes,
    response: bytes,
    imprint: bytes,
    nonce: int,
    bundle: _TrustBundle,
    approval: _Approval,
    *,
    qualify: bool = True,
) -> _ParsedEvent:
    import tempfile
    from pathlib import Path

    from matchvet.causal_trust import _authenticate, _openssl, _utc

    try:
        trust = _authenticate(bundle)
        approval.require(trust, bundle)
        event = _parse_response(response, trust.signer, trust.anchor)
        query_imprint, query_nonce = _query(request)
        # OpenSSL accepts a request without nonce. These comparisons are mandatory
        # independent application checks, even when cryptographic verification passes.
        if event.nonce != nonce or query_nonce != nonce:
            raise WitnessError("Exact signed/request nonce mismatch.")
        if event.imprint != imprint or query_imprint != imprint:
            raise WitnessError("Exact signed/request SHA-256 imprint mismatch.")
        approval.require(trust, bundle, event.lower, event.upper, qualify=qualify)
        with tempfile.TemporaryDirectory(prefix="matchvet-causal-signature-") as directory:
            work = Path(directory)
            for name, raw in (
                ("query.der", request),
                ("response.der", response),
                ("leaf.der", trust.signer),
                ("anchor.der", trust.anchor),
            ):
                (work / name).write_bytes(raw)
            for name in ("leaf", "anchor"):
                _openssl(
                    [
                        "x509",
                        "-inform",
                        "DER",
                        "-in",
                        str(work / (name + ".der")),
                        "-out",
                        str(work / (name + ".pem")),
                    ]
                )
            (work / "empty-ca").mkdir()
            _openssl(
                [
                    "ts",
                    "-verify",
                    "-queryfile",
                    str(work / "query.der"),
                    "-in",
                    str(work / "response.der"),
                    "-CAfile",
                    str(work / "anchor.pem"),
                    "-CApath",
                    str(work / "empty-ca"),
                    "-untrusted",
                    str(work / "leaf.pem"),
                    "-policy",
                    _POLICY,
                    "-attime",
                    str(int(_utc(event.lower).timestamp())),
                ]
            )
        return event
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError, OSError) as error:
        if isinstance(error, WitnessError):
            raise
        raise WitnessError("RFC3161/CMS/ASN.1 verification refused.") from error

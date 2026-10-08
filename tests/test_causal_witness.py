from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from matchvet.causal_trust import _AuthenticatedTrust
from matchvet.causal_witness import WitnessError, _event_interval, _Node, _parse_response


def test_signed_fraction_is_rounded_outward() -> None:
    assert _event_interval("20261005045021.0000001Z", {2: 1}) == (
        "2026-10-05T04:50:20.000000+00:00",
        "2026-10-05T04:50:22.000001+00:00",
    )


@pytest.mark.parametrize("accuracy", [None, {}, {2: 0}, {2: -1}, {2: 2}, {128: 1000}])
def test_no_guessed_accuracy(accuracy: dict[int, int] | None) -> None:
    with pytest.raises(WitnessError):
        _event_interval("20261005045021Z", accuracy)


WIRE = Path(__file__).resolve().parents[1] / "docs/research/cb01-sigstore-witness-2026-10-05"


def test_retained_wire_has_exact_signed_interval() -> None:
    value = _parse_response(
        (WIRE / "response.tsr").read_bytes(),
        (WIRE / "tsa-leaf.der").read_bytes(),
        (WIRE / "tsa-root.der").read_bytes(),
    )
    assert value.lower == "2026-10-05T04:50:20.000000+00:00"
    assert value.upper == "2026-10-05T04:50:22.000000+00:00"


def test_retained_trust_authenticates_rotations_and_interval() -> None:
    from matchvet.causal_trust import _authenticate, _TrustBundle

    bundle = _TrustBundle(
        tuple((WIRE / f"{v}.root.json").read_bytes() for v in range(11, 16)),
        (WIRE / "timestamp.json").read_bytes(),
        (WIRE / "snapshot.json").read_bytes(),
        (WIRE / "targets.json").read_bytes(),
        (WIRE / "trusted_root.json").read_bytes(),
    )
    value = _authenticate(bundle)
    assert value.signer == (WIRE / "tsa-leaf.der").read_bytes()
    assert value.anchor == (WIRE / "tsa-root.der").read_bytes()
    value.require_interval("2026-10-05T04:50:20.000000+00:00", "2026-10-05T04:50:22.000000+00:00")


def exact_wire_query() -> tuple[bytes, bytes, int]:
    from matchvet.causal_witness import _POLICY, _der, _imprint, _int, _node, _oid_der

    fields = _node((WIRE / "request.tsq").read_bytes(), 48).children()
    query = _der(
        48, fields[0].raw + fields[1].raw + _oid_der(_POLICY) + fields[2].raw + fields[3].raw
    )
    return query, _imprint(fields[1]), _int(fields[2])


def test_retained_wire_signature_and_trust_verify_independently() -> None:
    from causal_selection_support import approval, trust

    from matchvet.causal_witness import _verify_event

    query, imprint, nonce = exact_wire_query()
    event = _verify_event(
        query, (WIRE / "response.tsr").read_bytes(), imprint, nonce, trust(), approval()
    )
    assert event.upper == "2026-10-05T04:50:22.000000+00:00"


@pytest.mark.parametrize("field", ["nonce", "imprint"])
def test_nonce_and_imprint_are_mandatory_application_checks(field: str) -> None:
    from causal_selection_support import approval, trust

    from matchvet.causal_witness import _verify_event

    query, imprint, nonce = exact_wire_query()
    with pytest.raises(WitnessError, match=field):
        _verify_event(
            query,
            (WIRE / "response.tsr").read_bytes(),
            b"\0" * 32 if field == "imprint" else imprint,
            nonce + 1 if field == "nonce" else nonce,
            trust(),
            approval(),
        )


def wire_variant(case: str) -> bytes:
    from matchvet.causal_witness import _der, _node, _oid_der

    response = (WIRE / "response.tsr").read_bytes()
    top = list(_node(response, 48).children())
    info = list(top[1].children())
    cms = list(_node(info[1].content, 48).children())
    encap = list(cms[2].children())
    tst = list(_node(_node(encap[1].content, 4).content, 48).children())
    si = list(cms[4].children()[0].children())

    def node(tag: int, raw: bytes) -> _Node:
        return _node(_der(tag, raw), tag)

    if case == "status":
        return _der(48, _der(48, b"\x02\x01\x01") + top[1].raw)
    if case == "trailing":
        return response + b"\0"
    if case == "indefinite":
        return b"\x30\x80" + response[4:] + b"\0\0"
    if case == "nonminimal":
        return b"\x30\x83\0" + response[2:]
    if case == "missing-token":
        return _der(48, top[0].raw)
    if case == "duplicate-status":
        return _der(48, top[0].raw + top[0].raw + top[1].raw)
    accuracy = {
        "missing-accuracy": None,
        "empty-accuracy": b"",
        "zero-accuracy": b"\x02\x01\0",
        "negative-accuracy": b"\x02\x01\xff",
        "too-large-accuracy": b"\x02\x01\x02",
        "invalid-millis": b"\x80\x02\x03\xe8",
        "zero-millis": b"\x80\x01\0",
        "negative-micros": b"\x81\x01\xff",
        "unknown-accuracy": b"\x82\x01\x01",
        "duplicate-accuracy": b"\x02\x01\x01\x02\x01\x01",
        "unordered-accuracy": b"\x81\x01\x01\x80\x01\x01",
    }
    times = {
        "non-UTC": b"20261005045021+0000",
        "leap": b"20261005045060Z",
        "comma-fraction": b"20261005045021,1Z",
        "noncanonical-fraction": b"20261005045021.10Z",
        "unsupported-precision": b"20261005045021.1234567890123456789Z",
        "day-crossing": b"20261005000000Z",
    }
    if case in accuracy:
        value = accuracy[case]
        if value is None:
            del tst[5]
        else:
            tst[5] = node(48, value)
    elif case in times:
        tst[4] = node(24, times[case])
    elif case == "wrong-policy":
        tst[1] = _node(_oid_der("1.3.6.1.4.1.57264.3"), 6)
    elif case == "missing-nonce":
        del tst[6]
    elif case == "forged-nonce":
        tst[6] = node(2, b"\x01")
    elif case == "forged-imprint":
        imprint = list(tst[2].children())
        imprint[1] = node(4, b"\0" * 32)
        tst[2] = node(48, b"".join(n.raw for n in imprint))
    elif case == "duplicate-nonce":
        tst.insert(7, tst[6])
    elif case == "wrong-tsa":
        tst[7] = node(160, b"\x04\x01\0")
    elif case == "wrong-version":
        tst[0] = node(2, b"\x02")
    encap[1] = node(160, _der(4, _der(48, b"".join(n.raw for n in tst))))
    cms[2] = node(48, b"".join(n.raw for n in encap))
    if case == "wrong-signer-id":
        si[1] = node(48, b"\x30\0\x02\x01\x01")
    elif case == "wrong-signature-algorithm":
        si[4] = node(48, _oid_der("1.2.840.10045.4.3.3"))
    elif case == "wrong-digest-algorithm":
        si[2] = node(48, _oid_der("1.3.14.3.2.26"))
    elif case == "bad-signature":
        si[5] = node(4, si[5].content[:-1] + bytes([si[5].content[-1] ^ 1]))
    elif case in {"duplicate-attr", "missing-ESS", "wrong-ESS-hash"}:
        attrs = list(si[3].children())
        if case == "duplicate-attr":
            attrs.append(attrs[0])
            attrs.sort(key=lambda n: n.raw)
        elif case == "missing-ESS":
            attrs.pop()
        else:
            attrs[-1] = _node(
                attrs[-1].raw.replace(
                    (WIRE / "tsa-leaf.der").read_bytes()[:0]
                    + bytes.fromhex(
                        "85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7"
                    ),
                    b"\0" * 32,
                ),
                48,
            )
        si[3] = node(160, b"".join(n.raw for n in attrs))
    signer = _der(48, b"".join(n.raw for n in si))
    cms[4] = node(49, signer + (signer if case == "two-signers" else b""))
    if case == "extra-digest":
        cms[1] = node(49, cms[1].content * 2)
    elif case == "unapproved-certificate":
        cms[3] = node(160, (WIRE / "tsa-root.der").read_bytes())
    elif case == "wrong-CMS-version":
        cms[0] = node(2, b"\x01")
    info[1] = node(160, _der(48, b"".join(n.raw for n in cms)))
    return _der(48, top[0].raw + _der(48, b"".join(n.raw for n in info)))


@pytest.fixture(scope="module")
def wire_trust() -> _AuthenticatedTrust:
    from causal_selection_support import trust

    from matchvet.causal_trust import _authenticate

    return _authenticate(trust())


@pytest.mark.parametrize(
    "case",
    [
        "status",
        "trailing",
        "indefinite",
        "nonminimal",
        "missing-token",
        "duplicate-status",
        "missing-accuracy",
        "empty-accuracy",
        "zero-accuracy",
        "negative-accuracy",
        "too-large-accuracy",
        "invalid-millis",
        "zero-millis",
        "negative-micros",
        "unknown-accuracy",
        "duplicate-accuracy",
        "unordered-accuracy",
        "non-UTC",
        "leap",
        "comma-fraction",
        "noncanonical-fraction",
        "unsupported-precision",
        "day-crossing",
        "wrong-policy",
        "missing-nonce",
        "forged-nonce",
        "forged-imprint",
        "duplicate-nonce",
        "wrong-tsa",
        "wrong-version",
        "wrong-signer-id",
        "wrong-signature-algorithm",
        "wrong-digest-algorithm",
        "bad-signature",
        "duplicate-attr",
        "missing-ESS",
        "wrong-ESS-hash",
        "two-signers",
        "extra-digest",
        "unapproved-certificate",
        "wrong-CMS-version",
    ],
)
def test_malformed_or_forged_wire_never_qualifies(
    case: str, wire_trust: _AuthenticatedTrust, monkeypatch: pytest.MonkeyPatch
) -> None:
    from causal_selection_support import approval, trust

    from matchvet.causal_witness import _verify_event

    monkeypatch.setattr("matchvet.causal_trust._authenticate", lambda b: wire_trust)
    query, imprint, nonce = exact_wire_query()
    with pytest.raises(WitnessError):
        _verify_event(query, wire_variant(case), imprint, nonce, trust(), approval())


@pytest.mark.parametrize(
    "generalized,accuracy,expected",
    [
        (
            "20261005045021.1234567Z",
            {128: 1, 129: 1},
            ("2026-10-05T04:50:21.122455+00:00", "2026-10-05T04:50:21.124458+00:00"),
        ),
        (
            "20261005045021Z",
            {129: 1},
            ("2026-10-05T04:50:20.999999+00:00", "2026-10-05T04:50:21.000001+00:00"),
        ),
        (
            "20261005045021.5Z",
            {128: 500},
            ("2026-10-05T04:50:21.000000+00:00", "2026-10-05T04:50:22.000000+00:00"),
        ),
    ],
)
def test_exact_signed_accuracy_arithmetic(
    generalized: str, accuracy: dict[int, int], expected: tuple[str, str]
) -> None:
    assert _event_interval(generalized, accuracy) == expected


@pytest.mark.parametrize(
    "case", ["missing-rotation", "reordered-rotation", "unsigned-timestamp", "target-hash"]
)
def test_tuf_authentication_refuses_incomplete_or_modified_closure(case: str) -> None:
    from dataclasses import replace

    from causal_selection_support import trust

    from matchvet.causal_trust import _authenticate

    bundle = trust()
    if case == "missing-rotation":
        bundle = replace(bundle, roots=bundle.roots[:-1])
    elif case == "reordered-rotation":
        bundle = replace(bundle, roots=tuple(reversed(bundle.roots)))
    elif case == "unsigned-timestamp":
        bundle = replace(bundle, timestamp=bundle.timestamp.replace(b"799", b"800"))
    else:
        bundle = replace(bundle, trusted_root=bundle.trusted_root + b" ")
    with pytest.raises(WitnessError):
        _authenticate(bundle)


@pytest.mark.parametrize(
    "case",
    ["lower-floor", "higher-floor", "conflicting-hash", "missing-floor", "not-before", "expiry"],
)
def test_authenticated_floors_and_full_interval_are_required(
    case: str, wire_trust: _AuthenticatedTrust
) -> None:
    from dataclasses import replace

    from causal_selection_support import approval, trust

    state = approval()
    lower, upper = "2026-10-05T04:50:20.000000+00:00", "2026-10-05T04:50:22.000000+00:00"
    if case in {"lower-floor", "higher-floor", "conflicting-hash"}:
        floors = list(state.floors)
        role, version, digest = floors[1]
        floors[1] = (
            role,
            version - 1
            if case == "lower-floor"
            else version + 1
            if case == "higher-floor"
            else version,
            "0" * 64 if case == "conflicting-hash" else digest,
        )
        state = replace(state, floors=tuple(floors))
    elif case == "missing-floor":
        state = replace(state, floors=())
    elif case == "not-before":
        lower = "2025-07-03T23:59:59.000000+00:00"
    else:
        upper = "2026-11-21T00:00:00.000000+00:00"
    with pytest.raises(WitnessError):
        state.require(wire_trust, trust(), lower, upper)


@pytest.mark.parametrize("generalized", ["99991231235959Z", "00010101000000Z"])
def test_unsupported_interval_overflow_refuses(generalized: str) -> None:
    with pytest.raises(WitnessError, match="overflow"):
        _event_interval(generalized, {2: 1})


@pytest.mark.parametrize("kind", ["duck", "subclass"])
def test_transport_refuses_caller_constructed_precommit_queries(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.causal_selection import _WitnessAttempt
    from matchvet.causal_witness import _post

    class Duck:
        def _start_transport(self) -> bytes:
            return b"caller-built-precommit-query"

    class Forged(_WitnessAttempt):
        def _start_transport(self) -> bytes:
            return b"caller-built-precommit-query"

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Unissued query reached transport")

    monkeypatch.setattr("http.client.HTTPSConnection", forbidden)
    fake = Duck() if kind == "duck" else object.__new__(Forged)
    with pytest.raises(RuntimeError):
        _post(fake)  # type: ignore[arg-type]

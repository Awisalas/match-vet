from hashlib import sha256
from pathlib import Path

import pytest
from test_cb01_trust import _captured_trust

from matchvet.cb01_trust import SigstoreWitnessBackend, _parse_ts_query, trust_policy_body


@pytest.mark.parametrize(
    "filename,digest",
    [
        (
            "src/matchvet/cb01.py",
            "7de7f617d652329146a3fa3c4f2b9638134dfb3c8d4c931bb35b6a90ac200092",
        ),
        (
            "src/matchvet/cb01_trust.py",
            "4f75585163f353bc6dfcac1e566ee1502562d9a03b7c6e2b1fefc2800974c9be",
        ),
        (
            "docs/product-v2/CANDIDATE-INPUT-METHODOLOGY.md",
            "1ebeb80f33190f18440d2dcfa5b2526d3907223471f4b2711b7445b0ece8e200",
        ),
    ],
)
def test_released_cb01_software_and_method_010_remain_byte_identical(
    filename: str, digest: str
) -> None:
    root = Path(__file__).resolve().parents[1]
    assert sha256((root / filename).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "cutoff,kickoff,passes",
    [
        ("2026-10-05T04:50:21Z", "2026-10-05T05:00:00Z", False),
        ("2026-10-05T04:00:00Z", "2026-10-05T04:50:21Z", False),
        ("2026-10-05T04:50:20.9999999Z", "2026-10-05T04:50:21.0000001Z", True),
        ("2026-10-05T04:00:00Z", "2026-10-08T19:00:00Z", True),
    ],
)
def test_retained_signed_token_uses_exact_strict_witness_window(
    cutoff: str, kickoff: str, passes: bool
) -> None:
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "docs/research/cb01-sigstore-witness-2026-10-05"
    request = (fixtures / "request.tsq").read_bytes()
    query = _parse_ts_query(request)
    result = SigstoreWitnessBackend().verify_response(
        request,
        f"{query['nonce']:x}",
        (fixtures / "response.tsr").read_bytes(),
        _captured_trust(),
        trust_policy_body(),
        batch_digest=query["imprint"].hex(),
        cutoff_utc=cutoff,
        kickoff_utc=kickoff,
    )
    assert result.checks["signature"]["state"] == "PASSED"
    assert result.tsa["gen_time_utc"] == "2026-10-05T04:50:21Z"
    assert (result.checks["time_window"]["state"] == "PASSED") is passes

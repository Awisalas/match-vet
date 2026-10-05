from __future__ import annotations

import pytest

from matchvet.cb01_schema import (
    CB01SchemaError,
    canonical_bytes,
    compare_utc,
    decode_artifact,
    digest_bytes,
    encode_artifact,
)


def _failure_body() -> dict[str, object]:
    return {
        "batch_digest": "a" * 64,
        "attempt_digest": None,
        "attempt_result_digest": None,
        "verification_digest": None,
        "expected_preference_ids": ["market_a", "market_b"],
        "reasons": ["TSA_UNAVAILABLE"],
    }


def test_cb01_exact_envelope_round_trips_and_digest_is_content_addressed() -> None:
    content = encode_artifact("TimestampFailure", _failure_body())

    kind, body = decode_artifact(content)

    assert kind == "TimestampFailure"
    assert body == _failure_body()
    assert digest_bytes(content) == digest_bytes(
        canonical_bytes(
            {
                "body": _failure_body(),
                "contract_version": "cb01-v1",
                "kind": "TimestampFailure",
                "schema_version": 1,
            }
        )
    )


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "noncanonical"])
def test_cb01_rejects_duplicate_unknown_and_noncanonical_fields(mutation: str) -> None:
    valid = encode_artifact("TimestampFailure", _failure_body())
    content = {
        "duplicate": valid.replace(
            b'"kind":"TimestampFailure"',
            b'"kind":"TimestampFailure","kind":"TimestampFailure"',
        ),
        "unknown": valid.replace(
            b'"expected_preference_ids"', b'"extra":true,"expected_preference_ids"'
        ),
        "noncanonical": b" " + valid,
    }[mutation]

    with pytest.raises(CB01SchemaError):
        decode_artifact(content)


def test_cb01_rejects_incomplete_or_duplicate_denominator_entries() -> None:
    body = _failure_body()
    body["expected_preference_ids"] = ["market_a", "market_a"]

    with pytest.raises(CB01SchemaError):
        encode_artifact("TimestampFailure", body)


def test_cb01_timestamp_comparison_preserves_fractional_digits() -> None:
    assert compare_utc("2030-01-01T00:00:00.0000001Z", "2030-01-01T00:00:00.0000002Z") == -1
    assert compare_utc("2030-01-01T00:00:00.0000002Z", "2030-01-01T00:00:00.0000001Z") == 1
    assert compare_utc("2030-01-01T00:00:00.100Z", "2030-01-01T00:00:00.1Z") == 0

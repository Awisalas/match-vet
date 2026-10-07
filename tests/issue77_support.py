"""Retained offline RFC3161/TUF boundary for issue 77 and historical replay proofs."""

from __future__ import annotations

from hashlib import sha256

from test_cb01_repository import _TUF_FIXTURE, DeterministicWitnessBackend

from matchvet.cb01_trust import TimestampRequest, _parse_ts_query


class RetainedWitness(DeterministicWitnessBackend):
    """Synthetic responses with deterministic requests; no live TSA or randomness."""

    def create_request(self, batch_bytes: bytes) -> TimestampRequest:
        retained = (_TUF_FIXTURE / "request.tsq").read_bytes()
        query = _parse_ts_query(retained)
        imprint = query["imprint"]
        assert retained.count(imprint) == 1
        nonce = query["nonce"]
        nonce_bytes = nonce.to_bytes((nonce.bit_length() + 7) // 8, "big")
        assert retained.count(nonce_bytes) == 1
        next_nonce = nonce + self.request_count
        request = retained.replace(imprint, sha256(batch_bytes).digest()).replace(
            nonce_bytes, next_nonce.to_bytes(len(nonce_bytes), "big")
        )
        assert _parse_ts_query(request)["nonce"] == next_nonce
        return TimestampRequest(request, f"{next_nonce:x}")

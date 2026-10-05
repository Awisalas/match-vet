from __future__ import annotations

from matchvet.cb01_sources import _support


def test_candidate_input_reference_names_the_exact_f14_input_bundle() -> None:
    input_bundle_digest = "a" * 64
    support = _support(
        "match_winner_home",
        None,
        {},
        {"match_winner_home": {"candidate": "retained"}},
        input_bundle_digest,
        "b" * 64,
        "c" * 64,
        "d" * 64,
    )

    assert support["candidate_input"] == {
        "id": "f14-candidate-input:match_winner_home",
        "version": "f14-input-v2",
        "digest": input_bundle_digest,
        "state": "PRESENT",
        "reasons": [],
    }

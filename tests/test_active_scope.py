from dataclasses import replace

import pytest

from matchvet.active_scope import LEGACY_SEVEN_SCOPE, SUCCESSOR_SIX_SCOPE


def test_scope_is_fixed_ordered_and_digest_protected() -> None:
    scope = SUCCESSOR_SIX_SCOPE
    assert scope.league_keys == (
        "premier_league",
        "serie_a",
        "la_liga",
        "bundesliga",
        "ligue_1",
        "liga_portugal",
    )
    assert scope.digest == "sha256:47e48cdf62e8452b9ec869bb99771d975972d6b9514d48e62866bca8f29dbb54"
    assert scope.version == 2
    assert scope.season == "2026-27"
    assert LEGACY_SEVEN_SCOPE.version == 1
    assert LEGACY_SEVEN_SCOPE.league_keys == (*scope.league_keys, "belgian_pro_league")
    for changes in (
        {"league_keys": tuple(reversed(scope.league_keys))},
        {"league_keys": scope.league_keys[:-1]},
        {"league_keys": (*scope.league_keys, "belgian_pro_league")},
        {"season": "2025-26"},
        {"version": 3},
        {"version": True},
        {"contract_id": "wrong"},
        {"digest": "sha256:" + "0" * 64},
    ):
        with pytest.raises(ValueError):
            replace(scope, **changes)

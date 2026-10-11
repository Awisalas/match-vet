"""Fixed scope identities. Historical league identity availability is separate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

_SIX_KEYS: Final = (
    "premier_league",
    "serie_a",
    "la_liga",
    "bundesliga",
    "ligue_1",
    "liga_portugal",
)


@dataclass(frozen=True)
class ActiveScopeContract:
    contract_id: str
    version: int
    season: str
    league_keys: tuple[str, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version not in (1, 2):
            raise ValueError("Unsupported active-scope version.")
        keys = (*_SIX_KEYS, "belgian_pro_league") if self.version == 1 else _SIX_KEYS
        if (
            self.contract_id != f"matchvet-active-scope-v{self.version}"
            or self.season != "2026-27"
            or self.league_keys != keys
        ):
            raise ValueError(
                "Active scope must match its fixed identity, season and ordered leagues."
            )
        payload = {
            "contract_id": self.contract_id,
            "version": self.version,
            "season": self.season,
            "league_keys": self.league_keys,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        expected = f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
        if self.digest and self.digest != expected:
            raise ValueError("Active-scope digest does not match its canonical contract.")
        object.__setattr__(self, "digest", expected)


LEGACY_SEVEN_SCOPE: Final = ActiveScopeContract(
    "matchvet-active-scope-v1", 1, "2026-27", (*_SIX_KEYS, "belgian_pro_league")
)
SUCCESSOR_SIX_SCOPE: Final = ActiveScopeContract(
    "matchvet-active-scope-v2", 2, "2026-27", _SIX_KEYS
)

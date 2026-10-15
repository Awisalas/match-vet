"""Canonical owner-declared half-open windows for the five-league successor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Final

from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE, ActiveScopeContract

SLATE_WINDOW_CONTRACT_ID: Final = "matchvet-slate-window-v1"
SLATE_WINDOW_VERSION: Final = 1
SLATE_DISPLAY_ZONE: Final = "Africa/Lagos"
_LAGOS = timezone(timedelta(hours=1), name=SLATE_DISPLAY_ZONE)


def _canonical_utc(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp with an offset.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a time zone.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class SlateWindow:
    """Immutable interval identity; membership uses ``[start_utc, end_utc)``."""

    start_utc: str
    end_utc: str
    active_scope: ActiveScopeContract = SUCCESSOR_FIVE_SCOPE
    contract_id: str = SLATE_WINDOW_CONTRACT_ID
    version: int = SLATE_WINDOW_VERSION
    digest: str = ""

    def __post_init__(self) -> None:
        if (
            type(self.active_scope) is not ActiveScopeContract
            or self.active_scope != SUCCESSOR_FIVE_SCOPE
        ):
            raise ValueError("Slate Window requires the installed five-league active scope.")
        if self.contract_id != SLATE_WINDOW_CONTRACT_ID or self.version != SLATE_WINDOW_VERSION:
            raise ValueError("Unsupported Slate Window contract identity.")
        start = _canonical_utc(self.start_utc, "Slate Window start")
        end = _canonical_utc(self.end_utc, "Slate Window end")
        if start >= end:
            raise ValueError("Slate Window must end after start.")
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)
        payload = {
            "active_scope": {
                "contract_id": self.active_scope.contract_id,
                "digest": self.active_scope.digest,
                "version": self.active_scope.version,
            },
            "contract_id": self.contract_id,
            "display_timezone": SLATE_DISPLAY_ZONE,
            "end_utc": end,
            "start_utc": start,
            "version": self.version,
        }
        canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        expected = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if self.digest and self.digest != expected:
            raise ValueError("Slate Window digest does not match its canonical identity.")
        object.__setattr__(self, "digest", expected)

    @classmethod
    def from_owner_bounds(cls, start: str, end: str) -> SlateWindow:
        """Normalize offset-qualified owner bounds before assigning window identity."""
        return cls(start_utc=start, end_utc=end)

    @property
    def slate_id(self) -> str:
        return f"slate:{self.digest}"

    @property
    def start_lagos(self) -> str:
        return datetime.fromisoformat(self.start_utc).astimezone(_LAGOS).isoformat()

    @property
    def end_lagos(self) -> str:
        return datetime.fromisoformat(self.end_utc).astimezone(_LAGOS).isoformat()

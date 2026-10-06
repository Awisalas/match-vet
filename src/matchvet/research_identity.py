"""Stable logical Matchweek slots shared by storage guards and domain replay."""

from uuid import NAMESPACE_URL, uuid5


def logical_matchweek_id(season: str, friday: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"matchvet:logical-matchweek:{season}:{friday}"))


def selection_slot(matchweek_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"matchvet:matchweek-research-selection:{matchweek_id}"))


def completion_slot(matchweek_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"matchvet:matchweek-research-completion:{matchweek_id}"))


def is_reserved_research_slot(snapshot_id: str, matchweek_id: str) -> bool:
    return snapshot_id in (selection_slot(matchweek_id), completion_slot(matchweek_id))

"""Deterministic UTC and SQLite/filesystem fault boundaries for isolated tests."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from matchvet.matchweek_research import MatchweekResearchRepository, TrustedUTCUpperBound
from matchvet.research_identity import completion_slot, logical_matchweek_id, selection_slot
from matchvet.store import Store, open_store

BEFORE = datetime(2026, 9, 25, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 25, 13, tzinfo=UTC)
LOGICAL = logical_matchweek_id("2026-27", "2026-09-25")
SELECTION = selection_slot(LOGICAL)
RECEIPT = completion_slot(LOGICAL)


class Clock:
    def __init__(self, value: datetime = BEFORE) -> None:
        self.value = value

    def observe(self) -> TrustedUTCUpperBound:
        return TrustedUTCUpperBound(self.value, source="deterministic-test", confidence="TRUSTED")


class CommitBoundary:
    """Delegate real SQLite calls; inject immediately before/after actual commit."""

    def __init__(self, store: Store, callback: Callable[[str, str], None]) -> None:
        self.connection = store._connection_for_repository()
        self.callback = callback
        self.completed: set[str] = set()
        self.attempts: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)

    def commit(self) -> None:
        role = None
        for name, slot in (("selection", SELECTION), ("receipt", RECEIPT)):
            if (
                name not in self.completed
                and self.connection.execute(
                    "SELECT 1 FROM snapshot_manifests WHERE snapshot_id = ?", (slot,)
                ).fetchone()
                is not None
            ):
                role = name
        if role is not None:
            self.attempts.append(role)
            self.callback(role, "before")
        self.connection.commit()
        if role is not None:
            self.completed.add(role)
            self.callback(role, "after")


def install_commit_boundary(
    store: Store,
    callback: Callable[[str, str], None],
) -> CommitBoundary:
    boundary = CommitBoundary(store, callback)
    store._connection = cast(sqlite3.Connection, boundary)
    return boundary


def crash_worker(root: str, f16: str, mode: str) -> None:
    path = Path(root)
    with open_store(path / "store.sqlite3", private_root=path) as store:

        def committed(role: str, when: str) -> None:
            if mode == f"{role}_{when}_commit":
                os._exit(37)

        install_commit_boundary(store, committed)
        sync = os.fsync
        path_open = Path.open

        def sync_or_crash(descriptor: int) -> None:
            operation = store._research_owner
            if (
                mode == "receipt_staging"
                and operation is not None
                and operation._phase == "receipt_attempt"
            ):
                os._exit(37)
            sync(descriptor)

        def open_or_crash(self: Path, *args: Any, **kwargs: Any) -> Any:
            operation = store._research_owner
            if (
                mode == "after_observation"
                and operation is not None
                and operation._phase == "acknowledged"
            ):
                os._exit(37)
            return path_open(self, *args, **kwargs)

        with (
            patch("os.fsync", sync_or_crash),
            patch.object(Path, "open", open_or_crash),
            patch("matchvet.artifacts._utc_now", lambda: BEFORE.isoformat(timespec="microseconds")),
            patch("matchvet.store._utc_now", lambda: BEFORE.isoformat(timespec="microseconds")),
        ):
            MatchweekResearchRepository(store, clock=Clock()).seal_completed(f16)
    raise AssertionError("The chosen crash boundary was not reached.")

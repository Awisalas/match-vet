"""Offline reproductions retained by the adversarial review of commit 40118a4."""

from pathlib import Path
from typing import Any

import pytest
from source_authorization_support import SourceOwner, acquisition_manifest
from test_source_authorization import no_remote_network as no_remote_network

import matchvet.source_authorization as source_authorization
from matchvet.artifacts import ArtifactStore
from matchvet.cb01 import BootstrapRepository
from matchvet.source_authorization import SourceAuthorizationRepository
from matchvet.source_manifest import (
    SourceAuthorizationError,
    _closure,
    canonical,
    digest,
    verify_manifest,
)
from matchvet.store import Store, open_store
from matchvet.t10 import SettlementEvidence, T10GradingService


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#89: a withdrawal during post-checkpoint validation permits the side effect",
)
@pytest.mark.parametrize("checkpoint_boundary", [3, 7], ids=["dispatch", "admission"])
def test_withdrawal_during_final_validation_refuses_side_effect(
    checkpoint_boundary: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        dispatches: list[bytes] = []
        raw = b"review private raw source"

        def withdraw_after_validation(current_store: Store, identity: str) -> dict[str, Any]:
            value = verify_manifest(current_store, identity)
            # The fresh head has already been read. Withdraw while the guard
            # validates the manifest, before it returns to dispatch or commit.
            if owner.calls == checkpoint_boundary and len(owner.raws) == 1:
                owner.withdraw(manifest)
            return value

        def acquire() -> bytes:
            dispatches.append(raw)
            return raw

        monkeypatch.setattr(source_authorization, "verify_manifest", withdraw_after_validation)
        with pytest.raises(SourceAuthorizationError):
            SourceAuthorizationRepository(store).acquire(
                manifest, acquire, lambda _raw: b"review normalized source"
            )
        assert len(owner.raws) == 2, "The withdrawal was completed before the side effect."
        if checkpoint_boundary == 3:
            assert not dispatches, "Acquisition dispatched after completed withdrawal."
        else:
            assert store.artifact_metadata(digest(raw)) is None, (
                "Protected raw admission committed after completed withdrawal."
            )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#89: outcome closure does not follow retained SettlementEvidence.source_digest",
)
def test_outcome_source_digest_is_part_of_retained_closure(tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        artifacts = ArtifactStore(store)
        raw = artifacts.publish_artifact(b"exact outcome source response", "text/plain")
        evidence = SettlementEvidence(
            fixture_id="review-fixture",
            source_key="review-outcome-source",
            record_id="review-outcome",
            source_digest=raw.digest,
            fixture_status="FINISHED",
            full_time_home_goals=1,
            full_time_away_goals=0,
        )
        # These are the actual typed T10/F19 evidence fields inspected by the
        # closure walker. No missing-source or fabricated-digest fixture is used.
        root = artifacts.publish_artifact(
            canonical({"evidence": [evidence.to_dict()]}),
            "application/vnd.matchvet.review-outcome-evidence+json",
        )
        dependencies = _closure(store, (root.digest,))
        assert "artifact:" + raw.digest in {item["id"] for item in dependencies}


def test_cb01_accepts_supplemental_source_outside_settlement_snapshot(tmp_path: Path) -> None:
    """Establish the real downstream path omitted by the OUTCOME manifest projection."""
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        original = SettlementEvidence(
            fixture_id="review-fixture",
            source_key="reviewed-outcome-source",
            record_id="reviewed-outcome",
            fixture_status="FINISHED",
            full_time_home_goals=1,
            full_time_away_goals=0,
        )
        supplement = SettlementEvidence(
            fixture_id="review-fixture",
            source_level="FEDERATION",
            source_key="supplemental-source-outside-manifest",
            record_id="supplemental-corners",
            fixture_status="FINISHED",
            corners_home=3,
            corners_away=2,
        )
        T10GradingService(store).grade_fixture((supplement,), fixture_id="review-fixture")
        settlement = {"evidence": [original.to_dict()]}
        items = BootstrapRepository(store)._outcome_evidence_items(
            settlement, original.fixture_id, (supplement.evidence_digest,)
        )
        assert settlement["evidence"] == [original.to_dict()]
        assert {item["source_key"] for item in items} == {
            original.source_key,
            supplement.source_key,
        }

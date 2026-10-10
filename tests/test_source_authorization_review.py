"""Offline reproductions retained by the adversarial review of commit 40118a4."""

from pathlib import Path
from typing import Any

import pytest
from source_authorization_support import SourceOwner, acquisition_manifest
from test_source_authorization import no_remote_network as no_remote_network

import matchvet.source_authorization as source_authorization
from matchvet.artifacts import ArtifactError, ArtifactStore
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


@pytest.mark.parametrize(
    "checkpoint_boundary", [3, 7, 10], ids=["dispatch", "raw-admission", "normalized-admission"]
)
def test_withdrawal_during_final_validation_refuses_side_effect(
    checkpoint_boundary: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        dispatches: list[bytes] = []
        raw = b"review private raw source"

        def withdraw_after_validation(
            current_store: Store, identity: str, *, historical_inspection: bool = False
        ) -> dict[str, Any]:
            value = verify_manifest(
                current_store, identity, historical_inspection=historical_inspection
            )
            # Withdraw during the final boundary validation, before the next
            # checkpoint and before dispatch or transaction commit.
            if owner.calls == checkpoint_boundary - 1 and len(owner.raws) == 1:
                owner.withdraw(manifest)
            return value

        def acquire() -> bytes:
            dispatches.append(raw)
            return raw

        monkeypatch.setattr(source_authorization, "verify_manifest", withdraw_after_validation)
        with pytest.raises((SourceAuthorizationError, ArtifactError)):
            SourceAuthorizationRepository(store).acquire(
                manifest, acquire, lambda _raw: b"review normalized source"
            )
        assert len(owner.raws) == 2, "The withdrawal was completed before the side effect."
        if checkpoint_boundary == 3:
            assert not dispatches, "Acquisition dispatched after completed withdrawal."
        else:
            refused = raw if checkpoint_boundary == 7 else b"review normalized source"
            assert store.artifact_metadata(digest(refused)) is None, (
                "Protected admission committed after completed withdrawal."
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


@pytest.mark.parametrize("prefix", ["", "sha256:"])
@pytest.mark.parametrize("retain_raw", [True, False], ids=["retained-raw", "later-raw"])
def test_outcome_manifest_binds_evidence_and_raw_and_replays_offline(
    prefix: str, retain_raw: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from source_authorization_support import projection_entries

    from matchvet.f19 import SettlementRepository
    from matchvet.source_authorization import replay_decision
    from matchvet.source_manifest import (
        MANIFEST_MEDIA_TYPE,
        outcome_projection,
        read,
        retain_manifest,
    )

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        artifacts = ArtifactStore(store)
        raw_bytes = b"retained exact outcome source"
        raw_digest = digest(raw_bytes)
        raw = artifacts.publish_artifact(raw_bytes, "text/plain") if retain_raw else None
        evidence = SettlementEvidence(
            fixture_id="review-fixture",
            source_key="review-outcome-source",
            record_id="review-outcome",
            source_digest=prefix + raw_digest,
            fixture_status="FINISHED",
            full_time_home_goals=1,
            full_time_away_goals=0,
        ).to_dict()
        settlement = {
            "selection_digest": "1" * 64,
            "manifest_digest": "2" * 64,
            "evidence": [evidence],
        }
        root = artifacts.publish_artifact(canonical(settlement), "application/json")
        monkeypatch.setattr(
            "matchvet.source_manifest.selected_projection",
            lambda *_a: {"f16_manifest_digest": "2" * 64, "graph_digest": "3" * 64},
        )
        monkeypatch.setattr(
            SettlementRepository,
            "replay",
            lambda _self, identity: SimpleNamespace(to_dict=lambda: read_settlement(identity)),
        )

        def read_settlement(identity: str) -> dict[str, Any]:
            assert identity == root.digest
            return settlement

        projection = outcome_projection(store, "1" * 64, root.digest)
        entries = projection_entries(store, projection)
        manifest = retain_manifest(
            store,
            stage="OUTCOME",
            selection_digest="1" * 64,
            projection=projection,
            entries=entries,
        )
        value = verify_manifest(store, manifest)
        expected_dependencies = {
            "artifact:" + root.digest,
            "outcome-evidence:" + str(evidence["evidence_digest"]),
        }
        if retain_raw:
            expected_dependencies.add("artifact:" + raw_digest)
        assert {item["id"] for item in projection["dependencies"]} == expected_dependencies
        classified = next(
            item for item in entries if item["dependency_id"].startswith("outcome-evidence:")
        )
        assert classified["provider"] == "review-outcome-source"
        if retain_raw:
            assert classified["raw_identity"] == {
                "id": "artifact:" + raw_digest,
                "digest": raw_digest,
            }
        else:
            assert classified["raw_identity"] == {"id": "UNKNOWN", "digest": "UNKNOWN"}
        assert projection["fact_evidence_digests"] == [evidence["evidence_digest"]]
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        decision = SourceAuthorizationRepository(store).authorize(manifest)
        if not retain_raw:
            artifacts.publish_artifact(raw_bytes, "text/plain")
        owner.withdraw(manifest)
        owner.config_path.unlink()
        monkeypatch.setattr(
            source_authorization,
            "_checkpoint",
            lambda *_a: pytest.fail("Current authority in replay"),
        )
        monkeypatch.setattr(store, "artifact_catalog", lambda: pytest.fail("Unrelated Store scan"))
        assert replay_decision(store, decision)["state"] == "APPROVED"
        assert verify_manifest(store, manifest, historical_inspection=True) == value
        if not retain_raw:
            # Current use needs a new closure; later retention does not rewrite
            # the old authorization or its immutable historical replay.
            with pytest.raises(SourceAuthorizationError):
                verify_manifest(store, manifest)
            return
        assert raw is not None

        # A separately retained raw classification is mandatory and exact.
        for mutation in ("omitted-raw", "changed-raw", "changed-provider", "changed-evidence"):
            changed = read(store, manifest, MANIFEST_MEDIA_TYPE)
            if mutation == "omitted-raw":
                changed["entries"] = [
                    item
                    for item in changed["entries"]
                    if item["dependency_id"] != "artifact:" + raw.digest
                ]
            else:
                item = next(
                    item
                    for item in changed["entries"]
                    if item["dependency_id"].startswith("outcome-evidence:")
                )
                if mutation == "changed-raw":
                    item["raw_identity"]["digest"] = "0" * 64
                elif mutation == "changed-provider":
                    item["provider"] = "substituted-source"
                else:
                    changed["projection"]["fact_evidence_digests"] = ["0" * 64]
            altered = artifacts.publish_artifact(canonical(changed), MANIFEST_MEDIA_TYPE).digest
            with pytest.raises(SourceAuthorizationError):
                verify_manifest(store, altered)

        (tmp_path / raw.relative_path).write_bytes(b"changed raw outcome response")
        with pytest.raises((SourceAuthorizationError, ArtifactError)):
            verify_manifest(store, manifest)
        with pytest.raises(SourceAuthorizationError):
            replay_decision(store, decision)

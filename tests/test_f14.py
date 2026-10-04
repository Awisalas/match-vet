from __future__ import annotations

from pathlib import Path

import pytest

from matchvet.f14 import F14Error, PreferenceProfileRepository
from matchvet.store import open_store
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG


def test_profile_is_deterministic_and_keeps_capability_separate(tmp_path: Path) -> None:
    enabled = ("match_winner_home", "total_corners_over_9_5")
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = PreferenceProfileRepository(store)
        profile = repository.build_profile(enabled, profile_version="founder-v1")

        assert tuple(item.preference_id for item in profile.enabled_preferences) == tuple(
            sorted(enabled)
        )
        assert profile.capability_catalog_digest == DEFAULT_PREFERENCE_CATALOG.digest
        assert profile.capability_catalog_digest != profile.digest
        assert repository.replay(profile.digest) == profile
        assert repository.build_profile(enabled, profile_version="founder-v1") == profile


@pytest.mark.parametrize(
    "preference_id",
    (
        "match_goals_under_2_5",
        "cards_over_4_5",
        "match_goals_over_0_5",
        "total_corners_over_2_5",
        "asian_handicap_home_minus_0_5",
    ),
)
def test_profile_rejects_unapproved_banned_or_trivial_preference(
    tmp_path: Path, preference_id: str
) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = PreferenceProfileRepository(store)

        with pytest.raises(F14Error):
            repository.build_profile((preference_id,))


def test_profile_rejects_duplicate_enablement(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = PreferenceProfileRepository(store)

        with pytest.raises(F14Error):
            repository.build_profile(("match_winner_home", "match_winner_home"))


def test_decision_input_rejects_odds_fields_before_ranking() -> None:
    from matchvet.f14 import DecisionInputBundle

    with pytest.raises(F14Error):
        DecisionInputBundle(
            profile_digest="profile",
            evidence_digest="evidence",
            cutoff_id="cutoff",
            model_result_digest="model",
            policy={},
            candidate_inputs={"match_winner_home": {"decimal_odds": 1.75}},
        )


def test_decision_replays_f13_and_returns_avoid_when_quantitative_support_is_missing(
    tmp_path: Path,
) -> None:
    from test_match_evidence_cutoff import _freeze

    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f13 import ModelContractRepository
    from matchvet.f14 import DECISION_MEDIA_TYPE, DecisionInputBundle, DecisionRepository
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.t15 import PolicyVersion

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy = cutoffs.persist_policy(CutoffPolicy("test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, cutoff_policy)[0]
        evidence = F11EvidenceRepository(store).build(freeze, cutoff_policy, weather_client=None)
        model = ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=())
        profiles = PreferenceProfileRepository(store)
        profile = profiles.build_profile(("match_winner_home",), profile_version="founder-v1")
        bundle = DecisionInputBundle(
            profile_digest=profile.digest,
            evidence_digest=evidence.digest,
            cutoff_id=cutoff.cutoff_id,
            model_result_digest=model.digest,
            policy=PolicyVersion("research-v1").to_dict(),
            candidate_inputs={},
        )
        decisions = DecisionRepository(store)

        result = decisions.build_decision(bundle)

        assert result.status == "RESEARCH_ONLY"
        assert result.outcome == "AVOID MATCH"
        assert result.primary_preference_id is None
        assert result.confidence is None
        assert result.data_quality is None
        assert result.risk is None
        assert result.lineage["profile_digest"] == profile.digest
        assert result.to_dict()["status"] == "RESEARCH_ONLY"
        assert result.to_dict()["outcome"] == "AVOID MATCH"
        assert result.to_dict()["primary_preference_id"] is None
        assert len(result.to_dict()["preference_results"]) == 1
        metadata = store.artifact_metadata(result.digest)
        assert metadata is not None and metadata.media_type == DECISION_MEDIA_TYPE
        assert metadata.retention_class == "PROTECTED"
        assert decisions.replay(result.digest) == result

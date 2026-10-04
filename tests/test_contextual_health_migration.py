from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from test_provider_health_f09 import _contextual_record, _fixture_observation

from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.provider_health import provider_health_record_to_canonical_json
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import MIGRATIONS, StoreMode, open_store

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_migration14_preserves_fixture_store_and_old_canonical_bytes(tmp_path: Path) -> None:
    path = tmp_path / "matchvet.sqlite3"
    assessment, fixture = _fixture_observation()
    encoded = provider_health_record_to_canonical_json(fixture)
    with open_store(path, private_root=tmp_path, migrations=MIGRATIONS[:13]) as store:
        assert store.status.schema_version == 13
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many((fixture,))
    with open_store(path, private_root=tmp_path) as upgraded:
        assert upgraded.status.mode is StoreMode.READ_WRITE
        assert upgraded.status.schema_version == 14
        repository = ProviderHealthRepository(upgraded)
        restored = repository.get(fixture.digest)
        assert restored == fixture
        assert restored is not None
        assert provider_health_record_to_canonical_json(restored) == encoded
        assert repository.list_for_assessment(assessment.digest) == (fixture,)
        context = _contextual_record()
        repository.persist_many((context,))
        assert repository.get(context.digest) == context
    with open_store(path, private_root=tmp_path) as reopened:
        assert ProviderHealthRepository(reopened).get(context.digest) == context
        assert ProviderHealthRepository(reopened).get(fixture.digest) == fixture
    # A previous application cannot write the newly upgraded store.
    with open_store(path, private_root=tmp_path, migrations=MIGRATIONS[:13]) as old_application:
        assert old_application.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert old_application.status.issues[0].code == "MV-STORE-SCHEMA_TOO_NEW"


def test_failed_contextual_migration_rolls_back_and_fixture_replay_survives(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path = tmp_path / "matchvet.sqlite3"
    assessment, fixture = _fixture_observation()
    with open_store(path, private_root=tmp_path, migrations=MIGRATIONS[:13]) as store:
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many((fixture,))
    failing = (
        *MIGRATIONS[:13],
        replace(
            MIGRATIONS[13],
            statements=(*MIGRATIONS[13].statements, "INSERT INTO missing_f09_table VALUES (1)"),
        ),
    )
    with monkeypatch.context() as injected:
        injected.setattr("matchvet.store.MIGRATIONS", failing)
        with open_store(path, private_root=tmp_path, migrations=failing) as recovered:
            assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
            assert recovered.status.schema_version == 13
            assert recovered.status.issues[0].code == "MV-STORE-MIGRATION_FAILED"
            assert ProviderHealthRepository(recovered).get(fixture.digest) == fixture
    with open_store(path, private_root=tmp_path, migrations=MIGRATIONS[:13]) as old_store:
        assert old_store.status.mode is StoreMode.READ_WRITE
        assert old_store.status.schema_version == 13
        assert ProviderHealthRepository(old_store).get(fixture.digest) == fixture
    # Real upgrade succeeds only if the failed CREATE statements were rolled back.
    with open_store(path, private_root=tmp_path) as upgraded:
        assert upgraded.status.mode is StoreMode.READ_WRITE
        context = _contextual_record()
        repository = ProviderHealthRepository(upgraded)
        repository.persist_many((context,))
        assert repository.get(context.digest) == context
        assert repository.get(fixture.digest) == fixture

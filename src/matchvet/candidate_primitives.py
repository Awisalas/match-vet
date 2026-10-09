"""Protected canonical preimages for SQL-backed health dependencies of causal graphs."""

from __future__ import annotations

import hashlib
import json

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.store import Store

HEALTH_MEDIA_TYPE = "application/vnd.matchvet.f09-health-canonical.v1+json"


def health_preimage(store: Store, reference: str) -> bytes:
    rows = (
        store._connection_for_repository()
        .execute(
            """SELECT record_json FROM provider_health_records WHERE record_digest = ?
           UNION ALL
           SELECT record_json FROM contextual_provider_health_records WHERE record_digest = ?""",
            (reference, reference),
        )
        .fetchall()
    )
    try:
        if len(rows) != 1:
            raise ValueError("Missing or ambiguous exact health dependency.")
        value = json.loads(str(rows[0][0]))
        if value.pop("digest") != reference:
            raise ValueError("Health dependency identity differs.")
        content = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
        if "sha256:" + hashlib.sha256(content).hexdigest() != reference:
            raise ValueError("Health dependency canonical preimage differs.")
        return content
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ArtifactError(
            "MV-CAUSAL-HEALTH-PREIMAGE", "Invalid exact health dependency."
        ) from error


def retain_health(store: Store, artifacts: ArtifactStore, reference: str) -> None:
    artifacts.publish_artifact(
        health_preimage(store, reference),
        HEALTH_MEDIA_TYPE,
        expected_digest=reference.removeprefix("sha256:"),
    )


def verify_health(store: Store, reference: str) -> None:
    artifacts = ArtifactStore(store)
    digest = reference.removeprefix("sha256:")
    metadata = artifacts.verify_artifact(digest)
    if (metadata.media_type, metadata.retention_class) != (
        HEALTH_MEDIA_TYPE,
        "PROTECTED",
    ) or artifacts.read_artifact(digest) != health_preimage(store, reference):
        raise ArtifactError(
            "MV-CAUSAL-HEALTH-PREIMAGE", "Exact protected health dependency differs."
        )

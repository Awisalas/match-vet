"""Verify would-be CB01 publications against retained bytes without writing them."""

from matchvet.artifacts import ARTIFACT_MEDIA_TYPE, ArtifactRecord, ArtifactStore
from matchvet.cb01 import BootstrapRepository, CB01Error
from matchvet.cb01_schema import digest_bytes
from matchvet.cb01_sources import replay_fixture_sources
from matchvet.cb01_trust import WitnessBackend
from matchvet.store import Store


class RetainedCB01Artifacts(ArtifactStore):
    """Adapt historical CB01 reconstruction to an inspection-only artifact seam."""

    def publish_artifact(
        self,
        content: bytes,
        media_type: str = ARTIFACT_MEDIA_TYPE,
        *,
        expected_digest: str | None = None,
        retention_class: str = "PROTECTED",
    ) -> ArtifactRecord:
        digest = digest_bytes(content)
        metadata = self.store.artifact_metadata(digest)
        if (
            expected_digest not in {None, digest}
            or metadata is None
            or metadata.media_type != media_type
            or metadata.retention_class != retention_class
            or self.read_artifact(digest) != content
        ):
            raise ValueError("CB01 inspection requires exact already-retained publication bytes.")
        return ArtifactRecord(
            metadata.artifact_id,
            metadata.digest,
            metadata.media_type,
            metadata.byte_length,
            metadata.relative_path,
            metadata.created_at_utc,
            metadata.retention_class,
        )


class RetainedBootstrapRepository(BootstrapRepository):
    """Read retained CB01 receipts and failures using unchanged core validators."""

    def __init__(self, store: Store, *, witness_backend: WitnessBackend | None = None) -> None:
        super().__init__(store, witness_backend=witness_backend)
        self.artifacts = RetainedCB01Artifacts(store)

    def verify_failure_lineage(self, digest: str) -> None:
        failure = self._read_kind(digest, "TimestampFailure")
        batch_digest = failure["batch_digest"]
        batch = self._read_kind(batch_digest, "FixtureEnrollmentBatch")
        prepared = replay_fixture_sources(self.store, batch)
        self._assert_prepared_batch(prepared, batch_digest, batch)
        for entry, row in zip(batch["entries"], prepared.pre_enrollments, strict=True):
            if (entry["disposition"], entry["reasons"]) != (row["disposition"], row["reasons"]):
                raise CB01Error("Failed batch entry differs from exact prepared bytes.")
        if failure["expected_preference_ids"] != batch["expected_preference_ids"]:
            raise CB01Error("Failed attempt differs from the complete batch denominator.")
        attempt_digest = failure["attempt_digest"]
        result_digest = failure["attempt_result_digest"]
        verification_digest = failure["verification_digest"]
        if attempt_digest is None:
            if result_digest is not None or verification_digest is not None:
                raise CB01Error("Failed attempt lacks its controlling attempt identity.")
            return
        attempt = self._read_kind(attempt_digest, "TimestampAttempt")
        if attempt["batch_digest"] != batch_digest:
            raise CB01Error("Failed attempt belongs to another exact batch.")
        if result_digest is not None:
            result = self._read_kind(result_digest, "TimestampAttemptResult")
            if result["attempt_digest"] != attempt_digest:
                raise CB01Error("Failed result belongs to another exact attempt.")
        if verification_digest is not None:
            verification = self._read_kind(verification_digest, "TimestampVerification")
            if (
                verification["attempt_digest"] != attempt_digest
                or verification["attempt_result_digest"] != result_digest
                or verification["state"] != "FAILED"
            ):
                raise CB01Error("Failed verification belongs to another exact attempt/result.")
        if result_digest is not None:
            reconstructed = self._finish_result(batch_digest, attempt_digest, result_digest, batch)
            if digest not in reconstructed.failure_digests:
                raise CB01Error("Failed attempt did not reconstruct its exact retained failure.")

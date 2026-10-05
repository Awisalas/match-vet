"""Exact CB01 v1 enrollment, recovery, replay, and F19 attachment."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.cb01_schema import (
    BODY_KEYS,
    FACT_KEYS,
    MEDIA_TYPES,
    CB01SchemaError,
    canonical_bytes,
    decode_artifact,
    digest_bytes,
    encode_artifact,
    normalize_utc,
)
from matchvet.cb01_sources import (
    CB01SourceError,
    FixtureEnrollmentInput,
    PreparedSources,
    prepare_fixture_sources,
    replay_fixture_sources,
)
from matchvet.cb01_trust import (
    REQUEST_MEDIA_TYPE,
    RESPONSE_MEDIA_TYPE,
    ROOT_MEDIA_TYPE,
    SHA256_OID,
    SNAPSHOT_MEDIA_TYPE,
    TARGETS_MEDIA_TYPE,
    TIMESTAMP_MEDIA_TYPE,
    TRUSTED_ROOT_MEDIA_TYPE,
    TUF_METADATA_VERSION_FLOORS,
    CB01TrustError,
    SigstoreWitnessBackend,
    TimestampRequest,
    TimestampTransport,
    TimestampVerificationResult,
    TrustRefresh,
    WitnessBackend,
    bootstrap_root_artifact,
    trust_material_artifact,
    trust_material_body,
    trust_policy_artifact,
    trust_policy_body,
    trust_state_schema,
)
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f19 import SettlementRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.store import ArtifactMetadata, Store
from matchvet.t10 import (
    CORNER_FACTS,
    FULL_GOAL_FACTS,
    HALF_GOAL_FACTS,
    SETTLEMENT_RULES_NAME,
    SETTLEMENT_RULES_VERSION,
    SettlementEvidence,
    SettlementGradeRecorder,
    _active_evidence_records,
    _evidence_groups,
    _fact_group,
    _status_group,
)
from matchvet.t12 import SECOND_HALF_GOAL_MODEL_VERSION

CHECK_NAMES = (
    "status",
    "imprint",
    "nonce",
    "signature",
    "signer",
    "eku",
    "policy",
    "chain",
    "trusted_root",
    "certificate_validity_at_gen_time",
    "time_window",
    "denominator",
    "lineage",
)
_RAW_TRUST_TYPES = {
    ROOT_MEDIA_TYPE,
    TIMESTAMP_MEDIA_TYPE,
    SNAPSHOT_MEDIA_TYPE,
    TARGETS_MEDIA_TYPE,
    TRUSTED_ROOT_MEDIA_TYPE,
}


class CB01Error(ValueError):
    """Exact upstream, protected artifact, or append-only identity failed CB01."""


@dataclass(frozen=True)
class EnrollmentRow:
    preference_id: str
    disposition: str
    enrollment_digest: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BatchResult:
    batch_digest: str
    attempt_digest: str | None
    verification_digest: str | None
    publication_digest: str | None
    failure_digests: tuple[str, ...]
    state: str
    rows: tuple[EnrollmentRow, ...]


@dataclass(frozen=True)
class DenominatorRow:
    freeze_id: str
    membership_id: str
    fixture_id: str
    preference_id: str
    membership_state: str
    state: str
    batch_digest: str | None
    publication_digest: str | None
    enrollment_digest: str | None
    failure_digests: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DenominatorView:
    freeze_digest: str
    profile_digest: str
    rows: tuple[DenominatorRow, ...]


@dataclass(frozen=True)
class CaseView:
    publication_digest: str
    batch_digest: str
    verification_digest: str
    records: tuple[tuple[str, str, dict[str, Any]], ...]
    attachments: tuple[tuple[str, dict[str, Any]], ...]


class BootstrapRepository:
    """Own complete preference batches and their independent RFC 3161 chronology."""

    def __init__(self, store: Store, *, witness_backend: WitnessBackend | None = None) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)
        self.witness: WitnessBackend = witness_backend or SigstoreWitnessBackend()

    def enroll_fixture(
        self,
        request: FixtureEnrollmentInput,
        trust_policy_digest: str | None = None,
    ) -> BatchResult:
        """Prepare the exact F06/Profile denominator and run at most one normal attempt."""
        policy_body = trust_policy_body()
        policy_content = trust_policy_artifact()
        policy_digest = digest_bytes(policy_content)
        if trust_policy_digest is not None and trust_policy_digest != policy_digest:
            raise CB01Error("CB01 v1 accepts only its frozen Sigstore trust policy digest.")
        if digest_bytes(encode_artifact("TrustMaterial", trust_material_body())) != digest_bytes(
            trust_material_artifact()
        ):
            raise CB01Error("Pinned CB01 TrustMaterial identity is inconsistent.")

        prepared = prepare_fixture_sources(self.store, request)
        pre_digests: dict[str, str] = {}
        pre_bodies: dict[str, dict[str, Any]] = {}
        for body in prepared.pre_enrollments:
            preference_id = body["preference"]["id"]
            content = encode_artifact("PreEnrollment", body)
            digest = self._publish_kind("PreEnrollment", content)
            if preference_id in pre_digests:
                raise CB01Error("The exact Profile contains a duplicate enabled preference.")
            pre_digests[preference_id] = digest
            pre_bodies[preference_id] = body
        expected = list(prepared.expected_preference_ids)
        if expected != sorted(set(expected)) or set(pre_digests) != set(expected):
            raise CB01Error("Prepared rows do not equal the complete exact Profile denominator.")
        entries = [
            {
                "preference_id": preference_id,
                "pre_enrollment_digest": pre_digests[preference_id],
                "disposition": pre_bodies[preference_id]["disposition"],
                "reasons": pre_bodies[preference_id]["reasons"],
            }
            for preference_id in expected
        ]
        batch_body = {
            "anchor": prepared.anchor,
            "lineage": prepared.lineage,
            "expected_preference_ids": expected,
            "entries": entries,
        }
        batch_content = encode_artifact("FixtureEnrollmentBatch", batch_body)
        batch_digest = self._publish_kind("FixtureEnrollmentBatch", batch_content)
        self._assert_prepared_batch(prepared, batch_digest, batch_body)
        self._publish_kind("TrustMaterial", trust_material_artifact())
        published_policy_digest = self._publish_kind("TrustPolicy", policy_content)
        if published_policy_digest != policy_digest:
            raise CB01Error("Pinned CB01 TrustPolicy digest changed during publication.")

        receipts = self._publications_for_batch(batch_digest)
        if receipts:
            if len(receipts) != 1:
                raise CB01Error("Conflicting complete receipts exist for this exact batch.")
            return self._result_from_publication(receipts[0][0])
        attempts = self._attempts_for_batch(batch_digest)
        if attempts:
            if len(attempts) != 1:
                raise CB01Error("A normal enrollment cannot select among multiple attempts.")
            return self._drive_attempt(batch_digest, attempts[0][0], allow_send=False)

        request_artifact = self._unattached_request(batch_digest)
        if request_artifact is not None:
            attempt_digest = self._adopt_retained_request(
                batch_digest, request_artifact, 1, None, policy_digest
            )
            return self._drive_attempt(batch_digest, attempt_digest, allow_send=True)

        try:
            trust = self.witness.refresh_trust(policy_body)
            self._retain_trust(trust)
        except CB01TrustError, OSError, ValueError, RuntimeError:
            failure = self._failure(
                batch_digest,
                None,
                None,
                None,
                expected,
                ("SIGSTORE_TUF_REFRESH_FAILED",),
            )
            return self._result(batch_digest, None, None, None, (failure,), "INCOMPLETE", ())
        return self._new_attempt(
            batch_digest,
            batch_body,
            trust,
            1,
            None,
            policy_digest,
        )

    def resume(
        self,
        batch_digest: str,
        exact_attempt_digest: str,
        *,
        retry_failed: bool = False,
    ) -> BatchResult:
        """Reverify one exact retained attempt; send again only on explicit retry."""
        batch_body = self._read_kind(batch_digest, "FixtureEnrollmentBatch")
        attempt_body = self._read_kind(exact_attempt_digest, "TimestampAttempt")
        if attempt_body["batch_digest"] != batch_digest:
            raise CB01Error("The selected TimestampAttempt belongs to another exact batch.")
        attempts = self._attempts_for_batch(batch_digest)
        if exact_attempt_digest not in {digest for digest, _ in attempts}:
            raise CB01Error("Exact TimestampAttempt is not reconciled into the protected catalog.")
        if len(attempts) > 2:
            raise CB01Error("The exact fixture batch exceeds its two-attempt request budget.")
        result = self._drive_attempt(batch_digest, exact_attempt_digest, allow_send=False)
        if result.publication_digest is not None or not retry_failed:
            return result
        if attempt_body["attempt_number"] != 1 or len(attempts) != 1:
            raise CB01Error("Only one explicit retry is allowed after the normal attempt.")
        prior_result = self._attempt_result_for(exact_attempt_digest)
        if prior_result is None:
            raise CB01Error("The selected attempt has no durable failure result to retry.")
        if prior_result[1]["transport_state"] == "RECEIVED":
            verification = self._verification_for(exact_attempt_digest)
            if verification is not None and verification[1]["state"] == "VERIFIED":
                raise CB01Error("A verified normal attempt cannot be replaced by a retry.")
        try:
            prepared = replay_fixture_sources(self.store, batch_body)
            self._assert_prepared_batch(prepared, batch_digest, batch_body)
        except (CB01SourceError, CB01Error, ArtifactError, ValueError) as error:
            raise CB01Error(
                "Changed source lineage cannot be retried under the retained batch."
            ) from error
        policy_body = self._load_policy(attempt_body["trust_policy_digest"])
        try:
            trust = self.witness.refresh_trust(policy_body)
            self._retain_trust(trust)
        except CB01TrustError, OSError, ValueError, RuntimeError:
            failure = self._failure(
                batch_digest,
                exact_attempt_digest,
                prior_result[0],
                None,
                batch_body["expected_preference_ids"],
                ("SIGSTORE_TUF_REFRESH_FAILED_FOR_EXPLICIT_RETRY",),
            )
            return self._result(
                batch_digest,
                exact_attempt_digest,
                None,
                None,
                (failure,),
                "INCOMPLETE",
                (),
            )
        return self._new_attempt(
            batch_digest,
            batch_body,
            trust,
            2,
            exact_attempt_digest,
            attempt_body["trust_policy_digest"],
        )

    def replay(
        self,
        publication_digest: str,
        exact_attachment_digests: tuple[str, ...] = (),
    ) -> CaseView:
        """Replay one explicitly named complete publication and attachments."""
        publication = self._read_kind(publication_digest, "FixtureEnrollmentPublication")
        batch_digest = publication["batch_digest"]
        batch = self._read_kind(batch_digest, "FixtureEnrollmentBatch")
        verification = self._read_kind(publication["verification_digest"], "TimestampVerification")
        if verification["state"] != "VERIFIED":
            raise CB01Error("A publication cannot reference a failed timestamp verification.")
        attempt = self._read_kind(verification["attempt_digest"], "TimestampAttempt")
        if attempt["batch_digest"] != batch_digest:
            raise CB01Error("Published verification and batch identities disagree.")
        self._verify_retained_attempt(batch_digest, verification["attempt_digest"], attempt, batch)
        self._verify_publication_body(publication, batch_digest, batch)
        records: list[tuple[str, str, dict[str, Any]]] = []
        attempt_digest = verification["attempt_digest"]
        for item in publication["records"]:
            record = self._read_kind(item["enrollment_digest"], "EnrollmentRecord")
            if (
                record["batch_digest"] != batch_digest
                or record["attempt_digest"] != attempt_digest
                or record["request_digest"] != attempt["request_digest"]
                or record["response_digest"] != verification["response_digest"]
                or record["verification_digest"] != publication["verification_digest"]
                or record["trust_policy_digest"] != attempt["trust_policy_digest"]
                or record["trust_material_digest"] != verification["trust_material_digest"]
            ):
                raise CB01Error("Published EnrollmentRecord is not bound to its exact batch.")
            records.append((item["preference_id"], item["enrollment_digest"], record))
        attachments: list[tuple[str, dict[str, Any]]] = []
        if len(exact_attachment_digests) != len(set(exact_attachment_digests)):
            raise CB01Error("Exact attachment digest selection contains duplicates.")
        verified_outcome_digests: set[str] = set()
        verified_fact_digests: set[str] = set()
        selected_entries: list[tuple[str, str, dict[str, Any]]] = []
        for digest in exact_attachment_digests:
            kind, body = self._read_any_cb01(digest)
            if kind not in {"OutcomeAttachment", "OutcomeFactAttachment"}:
                raise CB01Error("Replay accepts only exact outcome attachment digests.")
            if body["enrollment_digest"] not in {item[1] for item in records}:
                raise CB01Error("Outcome attachment belongs to another enrollment record.")
            selected_entries.append((kind, digest, body))
        for kind, digest, body in selected_entries:
            if kind == "OutcomeAttachment":
                self._verify_outcome_attachment(
                    digest, body, verified_outcome_digests, verified_fact_digests
                )
        referenced_fact_digests = {
            body["fact_attachment_digest"]
            for kind, _, body in selected_entries
            if kind == "OutcomeAttachment" and body["fact_attachment_digest"] is not None
        }
        for kind, digest, body in selected_entries:
            if kind == "OutcomeFactAttachment":
                if digest not in referenced_fact_digests:
                    raise CB01Error(
                        "OutcomeFactAttachment is not named by a selected exact OutcomeAttachment."
                    )
                self._verify_outcome_fact_body(body, verified_fact_digests)
            attachments.append((kind, body))
        return CaseView(
            publication_digest,
            batch_digest,
            publication["verification_digest"],
            tuple(records),
            tuple(attachments),
        )

    def inspect_denominator(
        self,
        freeze_digest: str,
        profile_digest: str,
        exact_publication_digests: tuple[str, ...] = (),
    ) -> DenominatorView:
        """Show every frozen membership by enabled preference with exact selected receipts."""
        freeze = MatchweekMembershipRepository(self.store).get_by_digest(freeze_digest)
        if freeze is None or freeze.freeze_digest != freeze_digest:
            raise CB01Error("Exact F06 freeze digest is not retained.")
        profile = PreferenceProfileRepository(self.store).replay(profile_digest)
        preferences = tuple(item.preference_id for item in profile.enabled_preferences)
        if preferences != tuple(sorted(set(preferences))):
            raise CB01Error("Exact Profile denominator is not sorted and unique.")
        selected_receipts: dict[str, tuple[str, str, dict[str, Any], dict[str, Any]]] = {}
        if len(exact_publication_digests) != len(set(exact_publication_digests)):
            raise CB01Error("Exact publication digest selection contains duplicates.")
        for digest in exact_publication_digests:
            publication = self._read_kind(digest, "FixtureEnrollmentPublication")
            batch = self._read_kind(publication["batch_digest"], "FixtureEnrollmentBatch")
            if batch["anchor"]["freeze"]["digest"] != _bare_digest(freeze.freeze_digest):
                raise CB01Error("Selected publication belongs to another exact F06 freeze.")
            if batch["anchor"]["profile"]["digest"] != profile.digest:
                raise CB01Error("Selected publication belongs to another exact Profile.")
            self._verify_publication_body(publication, publication["batch_digest"], batch)
            self.replay(digest)
            for item in publication["records"]:
                preference_id = item["preference_id"]
                key = batch["anchor"]["membership"]["id"] + "\0" + preference_id
                if key in selected_receipts:
                    raise CB01Error(
                        "Conflicting selected receipts cover the same denominator pair."
                    )
                record = self._read_kind(item["enrollment_digest"], "EnrollmentRecord")
                selected_receipts[key] = (digest, publication["batch_digest"], batch, record)

        failure_index = self._failures_by_anchor(_bare_digest(freeze.freeze_digest), profile.digest)
        rows: list[DenominatorRow] = []
        for membership in freeze.memberships:
            included = membership.decision.value == "INCLUDED"
            for preference_id in preferences:
                pair_key = membership.membership_id + "\0" + preference_id
                failure_digests = tuple(sorted(failure_index.get(membership.membership_id, ())))
                if not included:
                    rows.append(
                        DenominatorRow(
                            freeze.freeze_id,
                            membership.membership_id,
                            membership.fixture_id,
                            preference_id,
                            membership.decision.value,
                            "EXCLUDED",
                            None,
                            None,
                            None,
                            (),
                            tuple(sorted(membership.reason_codes)),
                        )
                    )
                    continue
                selected = selected_receipts.get(pair_key)
                if selected is None:
                    rows.append(
                        DenominatorRow(
                            freeze.freeze_id,
                            membership.membership_id,
                            membership.fixture_id,
                            preference_id,
                            membership.decision.value,
                            "INCOMPLETE_FOR_NOT_ATTEMPTED" if not failure_digests else "INCOMPLETE",
                            None,
                            None,
                            None,
                            failure_digests,
                            ("NO_EXACT_SELECTED_PUBLICATION_FOR_DENOMINATOR_PAIR",),
                        )
                    )
                    continue
                publication_digest, batch_digest, batch, record = selected
                record_digest = next(
                    item["enrollment_digest"]
                    for item in self._read_kind(publication_digest, "FixtureEnrollmentPublication")[
                        "records"
                    ]
                    if item["preference_id"] == preference_id
                )
                rows.append(
                    DenominatorRow(
                        freeze.freeze_id,
                        membership.membership_id,
                        membership.fixture_id,
                        preference_id,
                        membership.decision.value,
                        record["disposition"],
                        batch_digest,
                        publication_digest,
                        record_digest,
                        failure_digests,
                        tuple(record["reasons"]),
                    )
                )
        return DenominatorView(
            freeze_digest,
            profile_digest,
            tuple(sorted(rows, key=lambda row: (row.membership_id, row.preference_id))),
        )

    def attach_outcome(
        self,
        enrollment_digest: str,
        settlement_digest: str,
        exact_fact_evidence: tuple[str, ...] | None = None,
        predecessor_digest: str | None = None,
    ) -> tuple[str, str]:
        """Append one exact F19 version and its separately replayable fact projection."""
        enrollment = self._read_kind(enrollment_digest, "EnrollmentRecord")
        if enrollment["disposition"] != "ENROLLED_LIVE":
            raise CB01Error("F19 outcomes may be attached only after live enrollment.")
        batch = self._read_kind(enrollment["batch_digest"], "FixtureEnrollmentBatch")
        pre = self._read_kind(enrollment["pre_enrollment_digest"], "PreEnrollment")
        publication = self._unique_publication_for_record(enrollment_digest, batch)
        if publication["verification_digest"] != enrollment["verification_digest"]:
            raise CB01Error("Enrollment record is not named by its exact verified publication.")
        settlement = SettlementRepository(self.store).replay(settlement_digest).to_dict()
        settlement_identity = self._settlement_identity(settlement, batch, pre)
        evidence_items = self._outcome_evidence_items(
            settlement,
            batch["anchor"]["fixture_id"],
            exact_fact_evidence,
        )
        predecessor_body: dict[str, Any] | None = None
        fact_predecessor_digest: str | None = None
        if predecessor_digest is None:
            if (
                settlement["correction_sequence"] != 0
                or settlement["predecessor_digest"] is not None
            ):
                raise CB01Error("An F19 correction requires its exact CB01 attachment predecessor.")
        else:
            predecessor_body = self._read_kind(predecessor_digest, "OutcomeAttachment")
            if (
                predecessor_body["enrollment_digest"] != enrollment_digest
                or settlement["predecessor_digest"] != predecessor_body["settlement_digest"]
                or settlement["correction_sequence"] != predecessor_body["correction_sequence"] + 1
            ):
                raise CB01Error("F19 and CB01 correction predecessor identities disagree.")
            fact_predecessor_digest = cast(str, predecessor_body["fact_attachment_digest"])
            previous_fact = self._read_kind(fact_predecessor_digest, "OutcomeFactAttachment")
            if (
                previous_fact["enrollment_digest"] != enrollment_digest
                or previous_fact["settlement_digest"] != predecessor_body["settlement_digest"]
            ):
                raise CB01Error("Exact F19 predecessor has a conflicting fact attachment.")
        fact_body = self._outcome_fact_body(
            enrollment_digest,
            settlement_digest,
            batch["anchor"],
            settlement["correction_sequence"],
            fact_predecessor_digest,
            evidence_items,
        )
        fact_content = encode_artifact("OutcomeFactAttachment", fact_body)
        fact_digest = digest_bytes(fact_content)
        attachment_body = {
            "enrollment_digest": enrollment_digest,
            "settlement_digest": settlement_digest,
            "settlement_identity": settlement_identity,
            "state": settlement["state"],
            "result": settlement["settlement_result"],
            "correction_sequence": settlement["correction_sequence"],
            "predecessor_digest": predecessor_digest,
            "fact_attachment_digest": fact_digest,
        }
        content = encode_artifact("OutcomeAttachment", attachment_body)
        retained_fact_candidates = self._outcome_fact_candidates(
            enrollment_digest,
            settlement_digest,
            settlement["correction_sequence"],
            fact_predecessor_digest,
        )
        if retained_fact_candidates and (
            len(retained_fact_candidates) != 1 or retained_fact_candidates[0] != fact_digest
        ):
            raise CB01Error("Conflicting same-identity OutcomeFactAttachment artifacts exist.")
        existing = self._outcome_successors(enrollment_digest, predecessor_digest)
        digest = digest_bytes(content)
        if existing:
            if len(existing) != 1 or existing[0][0] != digest:
                raise CB01Error("An outcome predecessor already has a conflicting successor.")
            existing_body = self._read_kind(digest, "OutcomeAttachment")
            self._read_kind(fact_digest, "OutcomeFactAttachment")
            self._verify_outcome_attachment(digest, existing_body)
            return digest, fact_digest
        self._publish_kind("OutcomeFactAttachment", fact_content)
        return self._publish_kind("OutcomeAttachment", content), fact_digest

    def _outcome_evidence_items(
        self,
        settlement: dict[str, Any],
        fixture_id: str,
        exact_fact_evidence: tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        """Use the full F19 snapshot plus only exact same-fixture T10 supplements."""
        settlement_evidence = cast(list[dict[str, Any]], settlement["evidence"])
        by_digest = {
            str(item["evidence_digest"]): item
            for item in settlement_evidence
            if isinstance(item, dict) and isinstance(item.get("evidence_digest"), str)
        }
        if len(by_digest) != len(settlement_evidence):
            raise CB01Error("Exact F19 evidence snapshot has duplicate or malformed identities.")
        if exact_fact_evidence is None:
            return settlement_evidence
        if len(exact_fact_evidence) != len(set(exact_fact_evidence)):
            raise CB01Error("Fact evidence selection contains duplicate digests.")
        requested = set(exact_fact_evidence)
        selected_f19 = requested & set(by_digest)
        if selected_f19 and selected_f19 != set(by_digest):
            raise CB01Error("Fact evidence must include the complete exact F19 evidence snapshot.")
        supplemental_ids = requested - set(by_digest)
        if not supplemental_ids:
            return settlement_evidence
        supplemental = {
            item.evidence_digest: item.to_dict()
            for item in SettlementGradeRecorder(self.store).evidence_sets(fixture_id)
            if item.fixture_id == fixture_id and item.evidence_digest in supplemental_ids
        }
        if set(supplemental) != supplemental_ids:
            raise CB01Error("Fact evidence names an absent exact same-fixture T10 snapshot.")
        combined = {**by_digest, **supplemental}
        return sorted(combined.values(), key=lambda item: str(item["evidence_id"]))

    def _new_attempt(
        self,
        batch_digest: str,
        batch_body: dict[str, Any],
        trust: TrustRefresh,
        attempt_number: int,
        predecessor_attempt_digest: str | None,
        policy_digest: str,
    ) -> BatchResult:
        batch_bytes = self.artifacts.read_artifact(batch_digest)
        try:
            request: TimestampRequest = self.witness.create_request(batch_bytes)
        except CB01TrustError, OSError, ValueError, RuntimeError:
            failure = self._failure(
                batch_digest,
                None,
                None,
                None,
                batch_body["expected_preference_ids"],
                ("RFC3161_REQUEST_CREATION_FAILED",),
            )
            return self._result(
                batch_digest,
                None,
                None,
                None,
                (failure,),
                "INCOMPLETE",
                (),
            )
        if not _is_positive_hex_nonce(request.nonce_hex):
            raise CB01Error("RFC3161 backend returned a malformed or non-positive nonce.")
        self._retain_trust(trust)
        request_media = _media_with_parameters(
            REQUEST_MEDIA_TYPE,
            {
                "batch": batch_digest,
                "nonce": request.nonce_hex,
                "state": _b64(canonical_bytes(trust.state)),
            },
        )
        request_digest = self._publish_raw(request.der, request_media)
        attempt_body = {
            "batch_digest": batch_digest,
            "request_digest": request_digest,
            "nonce_hex": request.nonce_hex,
            "trust_policy_digest": policy_digest,
            "attempt_number": attempt_number,
            "predecessor_attempt_digest": predecessor_attempt_digest,
        }
        attempt_digest = self._publish_kind(
            "TimestampAttempt", encode_artifact("TimestampAttempt", attempt_body)
        )
        return self._send_attempt(batch_digest, attempt_digest, request.der, batch_body)

    def _send_attempt(
        self,
        batch_digest: str,
        attempt_digest: str,
        request_der: bytes,
        batch_body: dict[str, Any],
    ) -> BatchResult:
        attempt = self._read_kind(attempt_digest, "TimestampAttempt")
        try:
            policy = self._load_policy(attempt["trust_policy_digest"])
            retained_request = self._read_raw(attempt["request_digest"], REQUEST_MEDIA_TYPE)
            if retained_request != request_der:
                raise CB01Error("Submitted request bytes differ from the exact retained request.")
            from matchvet.cb01_trust import _parse_ts_query

            query = _parse_ts_query(request_der)
            if (
                query["algorithm_oid"] != SHA256_OID
                or query["imprint"] != bytes.fromhex(batch_digest)
                or query["nonce"] != int(attempt["nonce_hex"], 16)
                or f"{query['nonce']:x}" != attempt["nonce_hex"]
                or query["cert_req"] is not True
            ):
                raise CB01Error("RFC3161 request does not bind exact batch digest and nonce.")
            self._load_attempt_trust(attempt, batch_digest)
        except CB01TrustError, CB01Error, ArtifactError, ValueError, TypeError, KeyError:
            failure = self._failure(
                batch_digest,
                attempt_digest,
                None,
                None,
                batch_body["expected_preference_ids"],
                ("RETAINED_REQUEST_OR_AUTHENTICATED_TRUST_REPLAY_FAILED",),
            )
            return self._result(
                batch_digest, attempt_digest, None, None, (failure,), "INCOMPLETE", ()
            )
        try:
            transport = self.witness.submit_request(request_der, policy)
        except OSError, RuntimeError, TimeoutError, ValueError:
            transport = TimestampTransport("UNAVAILABLE", None, ("TSA_TRANSPORT_UNAVAILABLE",))
        if transport.state not in {"RECEIVED", "UNAVAILABLE", "REJECTED", "MALFORMED"}:
            transport = TimestampTransport(
                "MALFORMED", transport.response, ("TSA_TRANSPORT_STATE_INVALID",)
            )
        response_digest: str | None = None
        reasons = tuple(sorted(set(transport.reasons)))
        if transport.response is not None:
            response_media = _media_with_parameters(
                RESPONSE_MEDIA_TYPE,
                {
                    "attempt": attempt_digest,
                    "transport": transport.state,
                    "reasons": _b64(canonical_bytes(list(reasons))),
                },
            )
            response_digest = self._publish_raw(transport.response, response_media)
        result_body = {
            "attempt_digest": attempt_digest,
            "response_digest": response_digest,
            "transport_state": transport.state,
            "reasons": list(reasons),
        }
        result_digest = self._publish_kind(
            "TimestampAttemptResult", encode_artifact("TimestampAttemptResult", result_body)
        )
        return self._finish_result(batch_digest, attempt_digest, result_digest, batch_body)

    def _drive_attempt(
        self, batch_digest: str, attempt_digest: str, *, allow_send: bool
    ) -> BatchResult:
        attempt = self._read_kind(attempt_digest, "TimestampAttempt")
        batch_body = self._read_kind(batch_digest, "FixtureEnrollmentBatch")
        if attempt["batch_digest"] != batch_digest:
            raise CB01Error("Retained attempt points at another batch.")
        result = self._attempt_result_for(attempt_digest)
        if result is None:
            response_metadata = self._response_for(attempt_digest)
            if response_metadata is not None:
                parameters = _media_parameters(response_metadata.media_type, RESPONSE_MEDIA_TYPE)
                if set(parameters) != {"attempt", "transport", "reasons"}:
                    raise CB01Error("Retained response metadata has unknown or missing fields.")
                if parameters["attempt"] != attempt_digest:
                    raise CB01Error("Retained response metadata identifies another attempt.")
                try:
                    reasons_value = json.loads(_unb64(parameters["reasons"]))
                except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
                    raise CB01Error("Retained response metadata is malformed.") from error
                if not isinstance(reasons_value, list) or any(
                    not isinstance(item, str) for item in reasons_value
                ):
                    raise CB01Error("Retained response reasons are malformed.")
                result_body = {
                    "attempt_digest": attempt_digest,
                    "response_digest": response_metadata.digest,
                    "transport_state": parameters.get("transport", "MALFORMED"),
                    "reasons": sorted(set(reasons_value)),
                }
                result_digest = self._publish_kind(
                    "TimestampAttemptResult",
                    encode_artifact("TimestampAttemptResult", result_body),
                )
                result = (result_digest, result_body)
            elif allow_send:
                request = self._read_raw(attempt["request_digest"], REQUEST_MEDIA_TYPE)
                if request is None:
                    raise CB01Error("Retained RFC3161 request is not available to submit.")
                return self._send_attempt(batch_digest, attempt_digest, request, batch_body)
            else:
                unavailable_result_body: dict[str, Any] = {
                    "attempt_digest": attempt_digest,
                    "response_digest": None,
                    "transport_state": "UNAVAILABLE",
                    "reasons": ["RETAINED_ATTEMPT_HAS_NO_RETAINED_RESPONSE"],
                }
                result_digest = self._publish_kind(
                    "TimestampAttemptResult",
                    encode_artifact("TimestampAttemptResult", unavailable_result_body),
                )
                result = (result_digest, unavailable_result_body)
        if result[1]["response_digest"] is None or result[1]["transport_state"] in {
            "UNAVAILABLE",
            "REJECTED",
        }:
            failure = self._failure(
                batch_digest,
                attempt_digest,
                result[0],
                None,
                batch_body["expected_preference_ids"],
                tuple(result[1]["reasons"]) or ("RFC3161_RESPONSE_UNAVAILABLE",),
            )
            return self._result(
                batch_digest, attempt_digest, None, None, (failure,), "INCOMPLETE", ()
            )
        return self._finish_result(batch_digest, attempt_digest, result[0], batch_body)

    def _finish_result(
        self,
        batch_digest: str,
        attempt_digest: str,
        result_digest: str,
        batch_body: dict[str, Any],
    ) -> BatchResult:
        attempt = self._read_kind(attempt_digest, "TimestampAttempt")
        result = self._read_kind(result_digest, "TimestampAttemptResult")
        if result["attempt_digest"] != attempt_digest:
            raise CB01Error("TimestampAttemptResult does not bind its exact attempt.")
        response_digest = result["response_digest"]
        if response_digest is None:
            failure = self._failure(
                batch_digest,
                attempt_digest,
                result_digest,
                None,
                batch_body["expected_preference_ids"],
                tuple(result["reasons"]) or ("RFC3161_RESPONSE_UNAVAILABLE",),
            )
            return self._result(
                batch_digest, attempt_digest, None, None, (failure,), "INCOMPLETE", ()
            )
        if result["transport_state"] in {"UNAVAILABLE", "REJECTED"}:
            failure = self._failure(
                batch_digest,
                attempt_digest,
                result_digest,
                None,
                batch_body["expected_preference_ids"],
                tuple(result["reasons"]) or (f"TSA_{result['transport_state']}",),
            )
            return self._result(
                batch_digest, attempt_digest, None, None, (failure,), "INCOMPLETE", ()
            )

        response = self._read_raw(response_digest, RESPONSE_MEDIA_TYPE)
        if response is None:
            raise CB01Error("Exact RFC 3161 response is not retained in the protected catalog.")
        request = self._read_raw(attempt["request_digest"], REQUEST_MEDIA_TYPE)
        if request is None:
            raise CB01Error("Exact RFC 3161 request is not retained in the protected catalog.")
        try:
            trust = self._load_attempt_trust(attempt, batch_digest)
            policy = self._load_policy(attempt["trust_policy_digest"])
        except CB01TrustError, CB01Error, ArtifactError, ValueError:
            failure = self._failure(
                batch_digest,
                attempt_digest,
                result_digest,
                None,
                batch_body["expected_preference_ids"],
                ("RETAINED_AUTHENTICATED_TRUST_REPLAY_FAILED",),
            )
            return self._result(
                batch_digest, attempt_digest, None, None, (failure,), "INCOMPLETE", ()
            )

        denominator_ok = False
        lineage_ok = False
        try:
            prepared = replay_fixture_sources(self.store, batch_body)
            self._assert_prepared_batch(prepared, batch_digest, batch_body)
            denominator_ok = self._denominator_replays(prepared, batch_body)
            # Exact replay passes even when a source is explicitly unavailable.
            # Live enrollment readiness is checked separately for each row.
            lineage_ok = True
        except CB01SourceError, CB01Error, ArtifactError, ValueError, KeyError, TypeError:
            prepared = None
        try:
            verification_result = self.witness.verify_response(
                request,
                attempt["nonce_hex"],
                response,
                trust,
                policy,
                batch_digest=batch_digest,
                cutoff_utc=batch_body["anchor"]["cutoff_utc"],
                kickoff_utc=batch_body["anchor"]["kickoff_utc"],
            )
        except CB01TrustError, OSError, RuntimeError, ValueError, TypeError:
            verification_result = _failed_verification("RFC3161_VERIFICATION_ERROR")
        checks = _verification_checks(verification_result.checks, denominator_ok, lineage_ok)
        if result["transport_state"] == "MALFORMED":
            checks["status"] = {
                "state": "FAILED",
                "reasons": sorted(set(checks["status"]["reasons"] + ["TSA_TRANSPORT_MALFORMED"])),
            }
        reasons = sorted(
            {
                reason
                for check in checks.values()
                if check["state"] != "PASSED"
                for reason in check["reasons"]
            }
            | set(verification_result.reasons)
        )
        state = (
            "VERIFIED" if all(check["state"] == "PASSED" for check in checks.values()) else "FAILED"
        )
        existing = self._verification_for(attempt_digest)
        verifier = (
            existing[1]["verifier"]
            if existing is not None
            else {
                "name": trust.state["verification_client"],
                "version": trust.state["verification_client_version"],
                "options": [
                    "RFC3161 CMS and TSA certificate verification",
                    "certificate validity at signed genTime",
                    "Sigstore TUF retained-state replay",
                ],
                "software_digest": _module_digest(),
            }
        )
        verification_body = {
            "attempt_digest": attempt_digest,
            "attempt_result_digest": result_digest,
            "response_digest": response_digest,
            "trust_policy_digest": attempt["trust_policy_digest"],
            "trust_material_digest": self._fixed_material_digest(),
            "tsa": verification_result.tsa,
            "chain_fingerprints": list(verification_result.chain_fingerprints),
            "trust_state": trust_state_schema(trust.state),
            "checks": checks,
            "verifier": verifier,
            "state": state,
            "reasons": reasons,
        }
        verification_content = encode_artifact("TimestampVerification", verification_body)
        verification_digest = self._publish_verification(
            attempt_digest, existing, verification_content
        )
        if state != "VERIFIED":
            failure = self._failure(
                batch_digest,
                attempt_digest,
                result_digest,
                verification_digest,
                batch_body["expected_preference_ids"],
                tuple(reasons) or ("TIMESTAMP_VERIFICATION_FAILED",),
            )
            return self._result(
                batch_digest,
                attempt_digest,
                verification_digest,
                None,
                (failure,),
                "INCOMPLETE",
                (),
            )
        if not denominator_ok or not lineage_ok or prepared is None:
            raise CB01Error("A verified timestamp cannot finalize an unreplayed source batch.")
        return self._publish_records(
            batch_digest,
            batch_body,
            prepared,
            attempt_digest,
            result_digest,
            verification_digest,
        )

    def _publish_records(
        self,
        batch_digest: str,
        batch_body: dict[str, Any],
        prepared: PreparedSources,
        attempt_digest: str,
        result_digest: str,
        verification_digest: str,
    ) -> BatchResult:
        pre_by_digest = {
            entry["pre_enrollment_digest"]: self._read_kind(
                entry["pre_enrollment_digest"], "PreEnrollment"
            )
            for entry in batch_body["entries"]
        }
        publication_entries: list[dict[str, str]] = []
        result_rows: list[EnrollmentRow] = []
        for entry in batch_body["entries"]:
            pre = pre_by_digest[entry["pre_enrollment_digest"]]
            ready = pre["disposition"] == "READY_FOR_WITNESS" and self._lineage_ready(
                pre["lineage"]
            )
            disposition = (
                "EXCLUDED"
                if pre["disposition"] == "EXCLUDED"
                else "ENROLLED_LIVE"
                if ready
                else "INCOMPLETE"
            )
            reasons = [] if disposition == "ENROLLED_LIVE" else list(pre["reasons"])
            if disposition == "INCOMPLETE" and not reasons:
                reasons = ["EXACT_UPSTREAM_LINEAGE_INCOMPLETE"]
            record_body = {
                "pre_enrollment_digest": entry["pre_enrollment_digest"],
                "batch_digest": batch_digest,
                "attempt_digest": attempt_digest,
                "request_digest": self._read_kind(attempt_digest, "TimestampAttempt")[
                    "request_digest"
                ],
                "response_digest": self._read_kind(result_digest, "TimestampAttemptResult")[
                    "response_digest"
                ],
                "verification_digest": verification_digest,
                "trust_policy_digest": self._read_kind(attempt_digest, "TimestampAttempt")[
                    "trust_policy_digest"
                ],
                "trust_material_digest": self._fixed_material_digest(),
                "disposition": disposition,
                "reasons": sorted(set(reasons)),
            }
            record_digest = self._publish_kind(
                "EnrollmentRecord", encode_artifact("EnrollmentRecord", record_body)
            )
            self._assert_unique_record_identity(
                batch_digest, entry["pre_enrollment_digest"], record_digest
            )
            publication_entries.append(
                {"preference_id": entry["preference_id"], "enrollment_digest": record_digest}
            )
            result_rows.append(
                EnrollmentRow(
                    entry["preference_id"],
                    disposition,
                    record_digest,
                    tuple(record_body["reasons"]),
                )
            )
        publication_body = {
            "batch_digest": batch_digest,
            "verification_digest": verification_digest,
            "records": publication_entries,
        }
        publication_content = encode_artifact("FixtureEnrollmentPublication", publication_body)
        existing = self._publications_for_batch(batch_digest)
        publication_digest = digest_bytes(publication_content)
        if existing and (len(existing) != 1 or existing[0][0] != publication_digest):
            raise CB01Error(
                "Conflicting publication receipts exist for this exact successful batch."
            )
        publication_digest = self._publish_kind("FixtureEnrollmentPublication", publication_content)
        return self._result(
            batch_digest,
            attempt_digest,
            verification_digest,
            publication_digest,
            (),
            "PUBLISHED",
            tuple(result_rows),
        )

    def _publish_verification(
        self,
        attempt_digest: str,
        existing: tuple[str, dict[str, Any]] | None,
        content: bytes,
    ) -> str:
        digest = digest_bytes(content)
        if existing is not None:
            if existing[0] != digest:
                raise CB01Error("Retained TimestampVerification conflicts with exact replay.")
            return existing[0]
        for candidate_digest, _ in self._artifacts_of_kind("TimestampVerification"):
            candidate = self._read_kind(candidate_digest, "TimestampVerification")
            if candidate["attempt_digest"] == attempt_digest and candidate_digest != digest:
                raise CB01Error(
                    "Conflicting TimestampVerification identities exist for an attempt."
                )
        return self._publish_kind("TimestampVerification", content)

    def _verify_retained_attempt(
        self,
        batch_digest: str,
        attempt_digest: str,
        attempt: dict[str, Any],
        batch: dict[str, Any],
    ) -> None:
        if attempt["batch_digest"] != batch_digest:
            raise CB01Error("Published TimestampAttempt belongs to another batch.")
        result = self._attempt_result_for_digest(attempt)
        if result is None or result[1]["transport_state"] != "RECEIVED":
            raise CB01Error("Publication does not have an exact received RFC3161 response.")
        verification = self._verification_for(attempt_digest)
        if verification is None or verification[1]["state"] != "VERIFIED":
            raise CB01Error("Publication has no exact verified TimestampVerification.")
        result_digest, _ = result
        self._finish_result(batch_digest, attempt_digest, result_digest, batch)
        after = self._verification_for(attempt_digest)
        if after is None or after[0] != verification[0]:
            raise CB01Error("Exact timestamp verification did not replay deterministically.")

    def _assert_prepared_batch(
        self,
        prepared: PreparedSources,
        batch_digest: str,
        batch_body: dict[str, Any],
    ) -> None:
        if digest_bytes(self.artifacts.read_artifact(batch_digest)) != batch_digest:
            raise CB01Error("Canonical batch digest does not match its exact protected bytes.")
        if prepared.anchor != batch_body["anchor"] or prepared.lineage != batch_body["lineage"]:
            raise CB01Error("Exact replayed upstream anchor or lineage changed.")
        expected = list(prepared.expected_preference_ids)
        entries = batch_body["entries"]
        if (
            batch_body["expected_preference_ids"] != expected
            or [item["preference_id"] for item in entries] != expected
        ):
            raise CB01Error("Retained batch lost, added, or reordered an enabled preference.")
        for row, entry in zip(prepared.pre_enrollments, entries, strict=True):
            if row["preference"]["id"] != entry["preference_id"]:
                raise CB01Error("PreEnrollment preference identity differs from its batch entry.")
            digest = entry["pre_enrollment_digest"]
            saved = self._read_kind(digest, "PreEnrollment")
            if canonical_bytes(saved) != canonical_bytes(row):
                raise CB01Error(
                    "Exact retained PreEnrollment changed from replayed upstream inputs."
                )

    def _denominator_replays(self, prepared: PreparedSources, batch_body: dict[str, Any]) -> bool:
        try:
            profile = PreferenceProfileRepository(self.store).replay(
                batch_body["anchor"]["profile"]["digest"]
            )
            ids = [item.preference_id for item in profile.enabled_preferences]
            return (
                ids == batch_body["expected_preference_ids"]
                and len(batch_body["entries"]) == len(ids)
                and len({item["preference_id"] for item in batch_body["entries"]}) == len(ids)
                and prepared.expected_preference_ids == tuple(ids)
            )
        except ValueError, KeyError, TypeError:
            return False

    @staticmethod
    def _lineage_ready(lineage: dict[str, Any]) -> bool:
        return all(
            lineage[key]["state"] == "PRESENT"
            for key in (
                "f06",
                "f07",
                "f10_catalog",
                "f10_requirements",
                "f11_evidence",
                "f13_input",
                "f13_result",
                "f13_history",
                "f14_profile",
                "f14_decision",
                "f14_policy",
                "f16_manifest",
                "f16_match_result",
            )
        )

    def _read_kind(self, digest: str, expected_kind: str) -> dict[str, Any]:
        if expected_kind not in BODY_KEYS:
            raise CB01Error("Internal CB01 artifact kind is unsupported.")
        try:
            metadata = self.artifacts.verify_artifact(digest)
            if (metadata.media_type, metadata.retention_class) != (
                MEDIA_TYPES[expected_kind],
                "PROTECTED",
            ):
                raise CB01Error("CB01 reference is not the exact protected media type.")
            content = self.artifacts.read_artifact(digest)
            kind, body = decode_artifact(content, expected_kind=expected_kind)
            if kind != expected_kind or digest_bytes(content) != digest:
                raise CB01Error("CB01 artifact digest or kind does not match its exact reference.")
            return body
        except (ArtifactError, CB01SchemaError, TypeError, ValueError) as error:
            if isinstance(error, CB01Error):
                raise
            raise CB01Error(
                f"Protected CB01 {expected_kind} artifact failed exact replay."
            ) from error

    def _read_any_cb01(self, digest: str) -> tuple[str, dict[str, Any]]:
        try:
            metadata = self.artifacts.verify_artifact(digest)
            if metadata.retention_class != "PROTECTED":
                raise CB01Error("CB01 artifacts must use protected retention.")
            content = self.artifacts.read_artifact(digest)
            kind, body = decode_artifact(content)
            if digest_bytes(content) != digest or metadata.media_type != MEDIA_TYPES[kind]:
                raise CB01Error("CB01 artifact media type or digest differs from its envelope.")
            return kind, body
        except (ArtifactError, CB01SchemaError, TypeError, ValueError, KeyError) as error:
            if isinstance(error, CB01Error):
                raise
            raise CB01Error("Exact protected CB01 attachment failed replay.") from error

    def _publish_kind(self, kind: str, content: bytes) -> str:
        try:
            decoded_kind, _ = decode_artifact(content, expected_kind=kind)
            if decoded_kind != kind:
                raise CB01Error("CB01 artifact envelope has the wrong exact kind.")
            record = self.artifacts.publish_artifact(
                content, MEDIA_TYPES[kind], retention_class="PROTECTED"
            )
            if record.digest != digest_bytes(content) or record.retention_class != "PROTECTED":
                raise CB01Error("CB01 protected publication returned a conflicting identity.")
            return record.digest
        except (ArtifactError, CB01SchemaError) as error:
            raise CB01Error(f"Unable to publish exact protected CB01 {kind} artifact.") from error

    def _publish_raw(self, content: bytes, media_type: str) -> str:
        digest = digest_bytes(content)
        existing = self.store.artifact_metadata(digest)
        if existing is not None and (
            existing.media_type,
            existing.retention_class,
            existing.byte_length,
        ) != (
            media_type,
            "PROTECTED",
            len(content),
        ):
            raise CB01Error("Conflicting protected raw artifact has the same content digest.")
        try:
            record = self.artifacts.publish_artifact(
                content, media_type, expected_digest=digest, retention_class="PROTECTED"
            )
        except ArtifactError as error:
            raise CB01Error("Unable to publish exact protected raw CB01 artifact.") from error
        return record.digest

    def _read_raw(self, digest: str, expected_media_type: str) -> bytes | None:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None:
            return None
        if metadata.retention_class != "PROTECTED" or not _has_media_base(
            metadata.media_type, expected_media_type
        ):
            raise CB01Error("Raw RFC3161 reference has a conflicting media type or retention.")
        byte_limit = 10_485_760 if expected_media_type == TRUSTED_ROOT_MEDIA_TYPE else 1_048_576
        if metadata.byte_length > byte_limit:
            raise CB01Error("Raw RFC3161 or Sigstore trust artifact exceeds its v1 byte bound.")
        return self.artifacts.read_artifact(digest)

    def _artifacts_of_kind(self, kind: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        output: list[tuple[str, dict[str, Any]]] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type == MEDIA_TYPES[kind]:
                output.append((metadata.digest, self._read_kind(metadata.digest, kind)))
        return tuple(output)

    def _attempts_for_batch(self, batch_digest: str) -> list[tuple[str, dict[str, Any]]]:
        attempts = [
            (digest, body)
            for digest, body in self._artifacts_of_kind("TimestampAttempt")
            if body["batch_digest"] == batch_digest
        ]
        numbers = [body["attempt_number"] for _, body in attempts]
        if len(numbers) != len(set(numbers)):
            raise CB01Error("Conflicting same-number TimestampAttempt artifacts exist.")
        if len(attempts) > 2:
            raise CB01Error("Retained attempts exceed the exact CB01 request budget.")
        attempts.sort(key=lambda item: item[1]["attempt_number"])
        for index, (_, body) in enumerate(attempts):
            if body["attempt_number"] != index + 1:
                raise CB01Error("Retained TimestampAttempt sequence has a gap.")
            expected_predecessor = attempts[index - 1][0] if index else None
            if body["predecessor_attempt_digest"] != expected_predecessor:
                raise CB01Error("Retained retry does not identify its exact prior attempt.")
        return attempts

    def _attempt_result_for(self, attempt_digest: str) -> tuple[str, dict[str, Any]] | None:
        matches = [
            (digest, body)
            for digest, body in self._artifacts_of_kind("TimestampAttemptResult")
            if body["attempt_digest"] == attempt_digest
        ]
        if len(matches) > 1:
            raise CB01Error("Conflicting TimestampAttemptResult artifacts exist for an attempt.")
        if matches:
            body = matches[0][1]
            response = self._response_for(attempt_digest)
            if body["response_digest"] is not None:
                if response is None or response.digest != body["response_digest"]:
                    raise CB01Error(
                        "Attempt result response is missing or has conflicting identity."
                    )
                parameters = _media_parameters(response.media_type, RESPONSE_MEDIA_TYPE)
                if (
                    set(parameters) != {"attempt", "transport", "reasons"}
                    or parameters["attempt"] != attempt_digest
                ):
                    raise CB01Error("Attempt result response metadata has unknown fields.")
                if (
                    parameters.get("transport") != body["transport_state"]
                    or sorted(set(json.loads(_unb64(parameters.get("reasons", "")))))
                    != body["reasons"]
                ):
                    raise CB01Error("Attempt result differs from exact retained response metadata.")
            elif response is not None:
                raise CB01Error("Attempt result omits its already retained RFC3161 response.")
            return matches[0]
        return None

    def _attempt_result_for_digest(
        self, attempt: dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        matches = self._attempt_result_for(self._digest_for_body("TimestampAttempt", attempt))
        return matches

    def _digest_for_body(self, kind: str, body: dict[str, Any]) -> str:
        content = encode_artifact(kind, body)
        return digest_bytes(content)

    def _verification_for(self, attempt_digest: str) -> tuple[str, dict[str, Any]] | None:
        matches = [
            (digest, body)
            for digest, body in self._artifacts_of_kind("TimestampVerification")
            if body["attempt_digest"] == attempt_digest
        ]
        if len(matches) > 1:
            raise CB01Error("Conflicting TimestampVerification artifacts exist for an attempt.")
        return matches[0] if matches else None

    def _response_for(self, attempt_digest: str) -> ArtifactMetadata | None:
        matches = []
        for metadata in self.store.artifact_catalog():
            if not _has_media_base(metadata.media_type, RESPONSE_MEDIA_TYPE):
                continue
            parameters = _media_parameters(metadata.media_type, RESPONSE_MEDIA_TYPE)
            if parameters.get("attempt") == attempt_digest:
                if metadata.retention_class != "PROTECTED":
                    raise CB01Error("RFC3161 response was not retained as protected evidence.")
                matches.append(metadata)
        if len(matches) > 1:
            raise CB01Error("Conflicting raw RFC3161 responses exist for one exact attempt.")
        return matches[0] if matches else None

    def _unattached_request(self, batch_digest: str) -> ArtifactMetadata | None:
        attempts = {body["request_digest"] for _, body in self._attempts_for_batch(batch_digest)}
        matches = []
        for metadata in self.store.artifact_catalog():
            if not _has_media_base(metadata.media_type, REQUEST_MEDIA_TYPE):
                continue
            parameters = _media_parameters(metadata.media_type, REQUEST_MEDIA_TYPE)
            if parameters.get("batch") == batch_digest and metadata.digest not in attempts:
                matches.append(metadata)
        if len(matches) > 1:
            raise CB01Error("Conflicting unassigned RFC3161 requests exist for one batch.")
        return matches[0] if matches else None

    def _adopt_retained_request(
        self,
        batch_digest: str,
        metadata: ArtifactMetadata,
        attempt_number: int,
        predecessor_digest: str | None,
        policy_digest: str,
    ) -> str:
        parameters = _media_parameters(metadata.media_type, REQUEST_MEDIA_TYPE)
        if parameters.get("batch") != batch_digest:
            raise CB01Error("Retained RFC3161 request is bound to another batch.")
        nonce = parameters.get("nonce", "")
        if not _is_positive_hex_nonce(nonce):
            raise CB01Error("Retained RFC3161 request nonce is malformed.")
        trust_state = _decode_trust_state(parameters.get("state", ""))
        request = self.artifacts.read_artifact(metadata.digest)
        from matchvet.cb01_trust import _parse_ts_query

        parsed = _parse_ts_query(request)
        if f"{parsed['nonce']:x}" != nonce:
            raise CB01Error("Retained RFC3161 request bytes differ from its nonce metadata.")
        body = {
            "batch_digest": batch_digest,
            "request_digest": metadata.digest,
            "nonce_hex": nonce,
            "trust_policy_digest": policy_digest,
            "attempt_number": attempt_number,
            "predecessor_attempt_digest": predecessor_digest,
        }
        digest = self._publish_kind("TimestampAttempt", encode_artifact("TimestampAttempt", body))
        _ = trust_state
        return digest

    def _load_policy(self, digest: str) -> dict[str, Any]:
        expected_content = trust_policy_artifact()
        if digest != digest_bytes(expected_content):
            raise CB01Error("TimestampAttempt names a non-v1 or conflicting TrustPolicy.")
        body = self._read_kind(digest, "TrustPolicy")
        if body != trust_policy_body():
            raise CB01Error("Retained TrustPolicy does not match the exact frozen CB01 policy.")
        self._read_kind(body["material_digest"], "TrustMaterial")
        return body

    def _retain_trust(self, trust: TrustRefresh) -> None:
        expected_state = trust_state_schema(trust.state)
        self._assert_tuf_metadata_not_rolled_back(trust, expected_state)
        for media_type, content in trust.retained_artifacts():
            if media_type not in _RAW_TRUST_TYPES:
                raise CB01Error("TUF refresh returned an unrecognized protected trust artifact.")
            self._publish_raw(content, media_type)
        if digest_bytes(bootstrap_root_artifact()) != expected_state["bootstrap_root_digest"]:
            raise CB01Error("Exact TUF bootstrap root differs from the TrustState identity.")
        if digest_bytes(trust.trusted_root) != expected_state["trusted_root_target_digest"]:
            raise CB01Error("Retained TrustedRoot bytes differ from the TrustState identity.")

    def _assert_tuf_metadata_not_rolled_back(
        self, trust: TrustRefresh, state: dict[str, Any]
    ) -> None:
        """Keep fresh TUF metadata at or above the v1 and locally retained version floors."""
        policy = trust_policy_body()
        metadata = {
            "root": trust.root_history[-1] if trust.root_history else bootstrap_root_artifact(),
            "timestamp": trust.timestamp,
            "snapshot": trust.snapshot,
            "targets": trust.targets,
        }
        version_keys = {
            "root": ("root_version", "root_digest"),
            "timestamp": ("timestamp_version", "timestamp_digest"),
            "snapshot": ("snapshot_version", "snapshot_digest"),
            "targets": ("targets_version", "targets_digest"),
        }
        seen: dict[str, dict[int, str]] = {role: {} for role in metadata}
        floors = {
            "root": int(policy["trust_update_policy"]["current_root_version"]),
            **TUF_METADATA_VERSION_FLOORS,
        }
        for role, minimum in floors.items():
            version_key, digest_key = version_keys[role]
            seen[role][minimum] = str(policy["trust_update_policy"]["metadata_digests"][role])
            if state[version_key] < minimum:
                raise CB01Error(
                    f"Fresh Sigstore TUF {role} metadata is below its v1 version floor."
                )
            if state[version_key] == minimum and state[digest_key] != seen[role][minimum]:
                raise CB01Error(
                    f"Fresh Sigstore TUF {role} metadata conflicts with its v1 version floor."
                )
            raw_digest = digest_bytes(metadata[role])
            raw_version = _tuf_document_version(metadata[role], role)
            if (raw_version, raw_digest) != (state[version_key], state[digest_key]):
                raise CB01Error(
                    f"Fresh Sigstore TUF {role} bytes differ from their exact identity."
                )

        for item in self.store.artifact_catalog():
            artifact_role = next(
                (
                    candidate_role
                    for candidate_role, media_type in (
                        ("root", ROOT_MEDIA_TYPE),
                        ("timestamp", TIMESTAMP_MEDIA_TYPE),
                        ("snapshot", SNAPSHOT_MEDIA_TYPE),
                        ("targets", TARGETS_MEDIA_TYPE),
                    )
                    if _has_media_base(item.media_type, media_type)
                ),
                None,
            )
            if artifact_role is None:
                continue
            content = self._read_raw(item.digest, item.media_type.split(";", 1)[0])
            if content is None:
                raise CB01Error("Retained Sigstore TUF metadata has no protected bytes.")
            version = _tuf_document_version(content, artifact_role)
            prior = seen[artifact_role].get(version)
            if prior is not None and prior != item.digest:
                raise CB01Error(
                    f"Conflicting retained Sigstore TUF {artifact_role} metadata version."
                )
            seen[artifact_role][version] = item.digest
        for role in metadata:
            version_key, digest_key = version_keys[role]
            current_version = state[version_key]
            current_digest = state[digest_key]
            prior_versions = seen[role]
            highest = max(prior_versions)
            if current_version < highest:
                raise CB01Error(
                    f"Fresh Sigstore TUF {role} metadata rolled back a retained version."
                )
            if current_version == highest and current_digest != prior_versions[highest]:
                raise CB01Error(
                    f"Fresh Sigstore TUF {role} metadata conflicts with a retained version."
                )
            prior_versions[current_version] = current_digest

    def _load_attempt_trust(self, attempt: dict[str, Any], batch_digest: str) -> TrustRefresh:
        request_metadata = self.store.artifact_metadata(attempt["request_digest"])
        if request_metadata is None or request_metadata.retention_class != "PROTECTED":
            raise CB01Error("Exact RFC3161 request is not reconciled into protected storage.")
        parameters = _media_parameters(request_metadata.media_type, REQUEST_MEDIA_TYPE)
        if set(parameters) != {"batch", "nonce", "state"}:
            raise CB01Error("Exact RFC3161 request metadata has unknown or missing fields.")
        if (
            parameters.get("batch") != batch_digest
            or parameters.get("nonce") != attempt["nonce_hex"]
        ):
            raise CB01Error("Exact RFC3161 request metadata differs from TimestampAttempt.")
        state = _decode_trust_state(parameters.get("state", ""))
        bootstrap = bootstrap_root_artifact()
        bootstrap_digest = digest_bytes(bootstrap)
        if self._read_raw(bootstrap_digest, ROOT_MEDIA_TYPE) != bootstrap:
            raise CB01Error(
                "Exact Sigstore bootstrap root v10 is not retained as protected evidence."
            )
        roots_by_version: dict[int, tuple[str, bytes]] = {}
        for metadata in self.store.artifact_catalog():
            if metadata.media_type != ROOT_MEDIA_TYPE:
                continue
            raw = self._read_raw(metadata.digest, ROOT_MEDIA_TYPE)
            if raw is None:
                continue
            try:
                parsed = json.loads(raw)
                version = int(parsed["signed"]["version"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise CB01Error("Retained Sigstore TUF root metadata is malformed.") from error
            prior = roots_by_version.get(version)
            if prior is not None and prior[0] != metadata.digest:
                raise CB01Error("Conflicting Sigstore TUF roots share an exact version.")
            roots_by_version[version] = (metadata.digest, raw)
        root_version = state["root_version"]
        root_history: list[bytes] = []
        for version in range(11, root_version + 1):
            selected = roots_by_version.get(version)
            if selected is None:
                raise CB01Error("A verified Sigstore TUF root rotation is not retained exactly.")
            root_history.append(selected[1])
        selected_root = roots_by_version.get(root_version)
        if selected_root is None or selected_root[0] != state["root_digest"]:
            raise CB01Error("Retained final Sigstore TUF root differs from TrustState identity.")
        timestamp = self._read_raw(state["timestamp_digest"], TIMESTAMP_MEDIA_TYPE)
        snapshot = self._read_raw(state["snapshot_digest"], SNAPSHOT_MEDIA_TYPE)
        targets = self._read_raw(state["targets_digest"], TARGETS_MEDIA_TYPE)
        trusted_root = self._read_raw(state["trusted_root_target_digest"], TRUSTED_ROOT_MEDIA_TYPE)
        if any(item is None for item in (timestamp, snapshot, targets, trusted_root)):
            raise CB01Error("Exact Sigstore TUF metadata or TrustedRoot bytes are not retained.")
        trust = self.witness.replay_trust(
            tuple(root_history),
            cast(bytes, timestamp),
            cast(bytes, snapshot),
            cast(bytes, targets),
            cast(bytes, trusted_root),
            self._load_policy(attempt["trust_policy_digest"]),
        )
        if trust_state_schema(trust.state) != state:
            raise CB01Error("Exact replayed Sigstore TUF identity differs from request metadata.")
        return trust

    def _failure(
        self,
        batch_digest: str,
        attempt_digest: str | None,
        attempt_result_digest: str | None,
        verification_digest: str | None,
        expected_preference_ids: list[str] | tuple[str, ...],
        reasons: tuple[str, ...],
    ) -> str:
        body = {
            "batch_digest": batch_digest,
            "attempt_digest": attempt_digest,
            "attempt_result_digest": attempt_result_digest,
            "verification_digest": verification_digest,
            "expected_preference_ids": sorted(set(expected_preference_ids)),
            "reasons": sorted(set(reasons)) or ["CB01_EVIDENCE_INCOMPLETE"],
        }
        return self._publish_kind("TimestampFailure", encode_artifact("TimestampFailure", body))

    def _publications_for_batch(self, batch_digest: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (digest, body)
            for digest, body in self._artifacts_of_kind("FixtureEnrollmentPublication")
            if body["batch_digest"] == batch_digest
        ]

    def _result_from_publication(self, publication_digest: str) -> BatchResult:
        case = self.replay(publication_digest)
        rows = tuple(
            EnrollmentRow(preference, body["disposition"], digest, tuple(body["reasons"]))
            for preference, digest, body in case.records
        )
        attempt_digest = self._read_kind(case.verification_digest, "TimestampVerification")[
            "attempt_digest"
        ]
        return self._result(
            case.batch_digest,
            attempt_digest,
            case.verification_digest,
            publication_digest,
            (),
            "PUBLISHED",
            rows,
        )

    @staticmethod
    def _result(
        batch_digest: str,
        attempt_digest: str | None,
        verification_digest: str | None,
        publication_digest: str | None,
        failure_digests: tuple[str, ...],
        state: str,
        rows: tuple[EnrollmentRow, ...],
    ) -> BatchResult:
        return BatchResult(
            batch_digest,
            attempt_digest,
            verification_digest,
            publication_digest,
            tuple(sorted(set(failure_digests))),
            state,
            rows,
        )

    def _verify_publication_body(
        self, publication: dict[str, Any], batch_digest: str, batch: dict[str, Any]
    ) -> None:
        if publication["batch_digest"] != batch_digest:
            raise CB01Error("Publication receipt does not identify its exact batch.")
        expected = batch["expected_preference_ids"]
        items = publication["records"]
        ids = [item["preference_id"] for item in items]
        if ids != expected or ids != sorted(set(ids)):
            raise CB01Error("Publication receipt does not cover the complete sorted denominator.")
        entries_by_id = {item["preference_id"]: item for item in batch["entries"]}
        for item in items:
            record = self._read_kind(item["enrollment_digest"], "EnrollmentRecord")
            entry = entries_by_id[item["preference_id"]]
            if record["pre_enrollment_digest"] != entry["pre_enrollment_digest"]:
                raise CB01Error("Publication record differs from exact PreEnrollment digest.")
            if record["batch_digest"] != batch_digest:
                raise CB01Error("Publication record belongs to another exact batch.")
            pre = self._read_kind(entry["pre_enrollment_digest"], "PreEnrollment")
            expected_disposition = (
                "EXCLUDED"
                if pre["disposition"] == "EXCLUDED"
                else "ENROLLED_LIVE"
                if pre["disposition"] == "READY_FOR_WITNESS" and self._lineage_ready(pre["lineage"])
                else "INCOMPLETE"
            )
            expected_reasons = (
                []
                if expected_disposition == "ENROLLED_LIVE"
                else pre["reasons"] or ["EXACT_UPSTREAM_LINEAGE_INCOMPLETE"]
            )
            if (
                record["disposition"] != expected_disposition
                or record["reasons"] != expected_reasons
            ):
                raise CB01Error("Publication record disposition differs from exact PreEnrollment.")

    def _assert_unique_record_identity(
        self, batch_digest: str, pre_digest: str, expected_digest: str
    ) -> None:
        for digest, body in self._artifacts_of_kind("EnrollmentRecord"):
            if (
                body["batch_digest"] == batch_digest
                and body["pre_enrollment_digest"] == pre_digest
                and digest != expected_digest
            ):
                raise CB01Error("Conflicting EnrollmentRecord exists for the same batch row.")

    def _unique_publication_for_record(
        self, enrollment_digest: str, batch: dict[str, Any]
    ) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for _, publication in self._artifacts_of_kind("FixtureEnrollmentPublication"):
            if any(
                item["enrollment_digest"] == enrollment_digest for item in publication["records"]
            ):
                if publication["batch_digest"] != self._digest_for_body(
                    "FixtureEnrollmentBatch", batch
                ):
                    raise CB01Error("Enrollment record is referenced by a different batch receipt.")
                matches.append(publication)
        if len(matches) != 1:
            raise CB01Error("Enrollment record must have exactly one complete publication receipt.")
        publication = matches[0]
        publication_digest = self._digest_for_body("FixtureEnrollmentPublication", publication)
        self.replay(publication_digest)
        return publication

    def _settlement_identity(
        self,
        settlement: dict[str, Any],
        batch: dict[str, Any],
        pre: dict[str, Any],
    ) -> dict[str, Any]:
        lineage = batch["lineage"]
        preference_id = pre["preference"]["id"]
        required = {
            "manifest_digest": _present_digest(lineage["f16_manifest"]),
            "match_result_digest": _present_digest(lineage["f16_match_result"]),
            "decision_digest": _present_digest(lineage["f14_decision"]),
            "fixture_id": batch["anchor"]["fixture_id"],
            "preference_id": preference_id,
        }
        if any(settlement.get(key) != value for key, value in required.items()):
            raise CB01Error("Exact F19 settlement differs from witnessed F16/F14 lineage.")
        if settlement.get("evidence_digest") is None:
            raise CB01Error("Exact F19 settlement has no evidence digest.")
        return {
            **required,
            "evidence_digest": settlement["evidence_digest"],
            "f19_correction_sequence": settlement["correction_sequence"],
            "f19_predecessor_digest": settlement["predecessor_digest"],
        }

    def _outcome_fact_body(
        self,
        enrollment_digest: str,
        settlement_digest: str,
        anchor: dict[str, Any],
        correction_sequence: int,
        predecessor_digest: str | None,
        evidence_values: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence = tuple(SettlementEvidence.from_mapping(item) for item in evidence_values)
        if any(item.fixture_id != anchor["fixture_id"] for item in evidence):
            raise CB01Error("Exact F19 fact evidence identifies another fixture.")
        active, _superseded = _active_evidence_records(evidence)
        groups = _evidence_groups(active)
        status_group, status_conflict = _status_group(groups)
        facts: dict[str, Any] = {}
        for fact_key in FACT_KEYS:
            selected, conflict, blocking = _fact_group(groups, (fact_key,))
            if selected is not None:
                value = selected.values_for((fact_key,))[0]
                records = _records_for(selected.evidence_ids, active)
                facts[fact_key] = _available_fact(value, selected.evidence_ids, records, fact_key)
            elif conflict:
                records = tuple(record for group in blocking for record in group.records)
                facts[fact_key] = _unavailable_fact(
                    "CONFLICTING", "T10_SOURCE_HIERARCHY_CONFLICT", records
                )
            elif status_group is not None and status_group.status_kinds == {"VOID"}:
                facts[fact_key] = _unavailable_fact(
                    "NOT_APPLICABLE", "T10_FIXTURE_STATUS_VOID", status_group.records
                )
            else:
                facts[fact_key] = _unavailable_fact(
                    "MISSING" if not status_conflict else "CONFLICTING",
                    "T10_FACT_NOT_AVAILABLE_IN_EXACT_F19_EVIDENCE"
                    if not status_conflict
                    else "T10_FIXTURE_STATUS_CONFLICT",
                    status_group.records if status_conflict and status_group is not None else (),
                )
        family_states = {
            "CORNERS": _family_state(groups, CORNER_FACTS),
            "FIRST_HALF_GOALS": _family_state(groups, HALF_GOAL_FACTS),
            "FULL_TIME_GOALS": _family_state(groups, FULL_GOAL_FACTS),
            "SECOND_HALF_GOALS": _family_state(
                groups,
                HALF_GOAL_FACTS,
                derivation_rule=_t12_rule_reference(),
            ),
        }
        return {
            "enrollment_digest": enrollment_digest,
            "settlement_digest": settlement_digest,
            "anchor": anchor,
            "evidence_snapshot_digests": sorted(
                {settlement_digest, *(item.evidence_digest for item in evidence)}
            ),
            "resolution_rule": _t10_rule_reference(),
            "facts": facts,
            "family_states": family_states,
            "correction_sequence": correction_sequence,
            "predecessor_digest": predecessor_digest,
        }

    def _outcome_successors(
        self, enrollment_digest: str, predecessor_digest: str | None
    ) -> list[tuple[str, dict[str, Any]]]:
        return [
            (digest, body)
            for digest, body in self._artifacts_of_kind("OutcomeAttachment")
            if body["enrollment_digest"] == enrollment_digest
            and body["predecessor_digest"] == predecessor_digest
        ]

    def _outcome_fact_candidates(
        self,
        enrollment_digest: str,
        settlement_digest: str,
        correction_sequence: int,
        predecessor_digest: str | None,
    ) -> list[str]:
        return [
            digest
            for digest, body in self._artifacts_of_kind("OutcomeFactAttachment")
            if body["enrollment_digest"] == enrollment_digest
            and body["settlement_digest"] == settlement_digest
            and body["correction_sequence"] == correction_sequence
            and body["predecessor_digest"] == predecessor_digest
        ]

    def _verify_outcome_attachment(
        self,
        attachment_digest: str,
        body: dict[str, Any],
        verified_digests: set[str] | None = None,
        verified_fact_digests: set[str] | None = None,
    ) -> None:
        verified_digests = verified_digests if verified_digests is not None else set()
        verified_fact_digests = (
            verified_fact_digests if verified_fact_digests is not None else set()
        )
        if attachment_digest in verified_digests:
            successors = self._outcome_successors(
                body["enrollment_digest"], body["predecessor_digest"]
            )
            if len(successors) != 1 or successors[0][0] != attachment_digest:
                raise CB01Error("Outcome predecessor has conflicting or missing exact successors.")
            return
        enrollment = self._read_kind(body["enrollment_digest"], "EnrollmentRecord")
        if enrollment["disposition"] != "ENROLLED_LIVE":
            raise CB01Error("Outcome attachment is not bound to live enrollment.")
        batch = self._read_kind(enrollment["batch_digest"], "FixtureEnrollmentBatch")
        pre = self._read_kind(enrollment["pre_enrollment_digest"], "PreEnrollment")
        settlement = SettlementRepository(self.store).replay(body["settlement_digest"]).to_dict()
        if (
            body["settlement_identity"] != self._settlement_identity(settlement, batch, pre)
            or body["state"] != settlement["state"]
            or body["result"] != settlement["settlement_result"]
            or body["correction_sequence"] != settlement["correction_sequence"]
        ):
            raise CB01Error("Outcome attachment differs from the exact replayed F19 version.")
        previous_fact_digest: str | None = None
        if body["predecessor_digest"] is None:
            if (
                settlement["correction_sequence"] != 0
                or settlement["predecessor_digest"] is not None
            ):
                raise CB01Error("Initial outcome attachment cannot skip an F19 predecessor.")
        else:
            previous = self._read_kind(body["predecessor_digest"], "OutcomeAttachment")
            self._verify_outcome_attachment(
                body["predecessor_digest"],
                previous,
                verified_digests,
                verified_fact_digests,
            )
            if (
                previous["enrollment_digest"] != body["enrollment_digest"]
                or settlement["predecessor_digest"] != previous["settlement_digest"]
                or settlement["correction_sequence"] != previous["correction_sequence"] + 1
            ):
                raise CB01Error("Outcome correction chain differs from exact F19 correction order.")
            previous_fact_digest = cast(str, previous["fact_attachment_digest"])
        successors = self._outcome_successors(body["enrollment_digest"], body["predecessor_digest"])
        if len(successors) != 1 or successors[0][0] != attachment_digest:
            raise CB01Error("Outcome predecessor has conflicting or missing exact successors.")
        fact_digest = body["fact_attachment_digest"]
        if fact_digest is None:
            raise CB01Error("Outcome attachment is missing its exact OutcomeFactAttachment.")
        fact = self._read_kind(fact_digest, "OutcomeFactAttachment")
        self._verify_outcome_fact_body(fact, verified_fact_digests)
        if (
            fact["enrollment_digest"] != body["enrollment_digest"]
            or fact["settlement_digest"] != body["settlement_digest"]
            or fact["correction_sequence"] != body["correction_sequence"]
            or fact["predecessor_digest"] != previous_fact_digest
        ):
            raise CB01Error("Outcome and fact attachment identities disagree.")
        verified_digests.add(attachment_digest)

    def _verify_outcome_fact_body(
        self, body: dict[str, Any], verified_digests: set[str] | None = None
    ) -> None:
        verified_digests = verified_digests if verified_digests is not None else set()
        fact_digest = self._digest_for_body("OutcomeFactAttachment", body)
        if fact_digest in verified_digests:
            return
        enrollment = self._read_kind(body["enrollment_digest"], "EnrollmentRecord")
        if enrollment["disposition"] != "ENROLLED_LIVE":
            raise CB01Error("Fact attachment is not bound to live enrollment.")
        batch = self._read_kind(enrollment["batch_digest"], "FixtureEnrollmentBatch")
        if body["anchor"] != batch["anchor"]:
            raise CB01Error("Fact attachment anchor differs from witnessed fixture anchor.")
        settlement = SettlementRepository(self.store).replay(body["settlement_digest"]).to_dict()
        snapshot_digests = body["evidence_snapshot_digests"]
        if body["settlement_digest"] not in snapshot_digests:
            raise CB01Error("Fact attachment omits its exact F19 settlement snapshot.")
        all_evidence = cast(list[dict[str, Any]], settlement["evidence"])
        available = {
            str(item["evidence_digest"])
            for item in all_evidence
            if isinstance(item, dict) and isinstance(item.get("evidence_digest"), str)
        }
        selected = set(snapshot_digests) - {body["settlement_digest"]}
        if not available <= selected:
            raise CB01Error(
                "Fact attachment omits part of its complete exact F19 evidence snapshot."
            )
        evidence_items = self._outcome_evidence_items(
            settlement,
            batch["anchor"]["fixture_id"],
            tuple(sorted(selected)),
        )
        previous_fact_digest = body["predecessor_digest"]
        if body["correction_sequence"] == 0:
            if previous_fact_digest is not None or settlement["predecessor_digest"] is not None:
                raise CB01Error("Initial fact attachment cannot skip a correction predecessor.")
        else:
            if previous_fact_digest is None:
                raise CB01Error("Corrected fact attachment is missing its exact predecessor.")
            previous = self._read_kind(previous_fact_digest, "OutcomeFactAttachment")
            self._verify_outcome_fact_body(previous, verified_digests)
            if (
                previous["enrollment_digest"] != body["enrollment_digest"]
                or previous["correction_sequence"] + 1 != body["correction_sequence"]
                or settlement["predecessor_digest"] != previous["settlement_digest"]
            ):
                raise CB01Error("Fact attachment correction chain differs from exact F19 lineage.")
        expected = self._outcome_fact_body(
            body["enrollment_digest"],
            body["settlement_digest"],
            batch["anchor"],
            body["correction_sequence"],
            previous_fact_digest,
            evidence_items,
        )
        if body != expected:
            raise CB01Error("OutcomeFactAttachment does not replay from its exact T10 evidence.")
        verified_digests.add(fact_digest)

    def _failures_by_anchor(self, freeze_digest: str, profile_digest: str) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        for failure_digest, failure in self._artifacts_of_kind("TimestampFailure"):
            try:
                batch = self._read_kind(failure["batch_digest"], "FixtureEnrollmentBatch")
            except CB01Error:
                continue
            anchor = batch["anchor"]
            if (
                anchor["freeze"]["digest"] == freeze_digest
                and anchor["profile"]["digest"] == profile_digest
            ):
                output.setdefault(anchor["membership"]["id"], []).append(failure_digest)
        return output

    def _fixed_material_digest(self) -> str:
        return digest_bytes(trust_material_artifact())


def _verification_checks(
    checks: dict[str, dict[str, Any]], denominator_ok: bool, lineage_ok: bool
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for name in CHECK_NAMES:
        item = checks.get(name, {"state": "UNPERFORMED", "reasons": ["CHECK_NOT_PERFORMED"]})
        if name == "denominator":
            item = (
                {"state": "PASSED", "reasons": []}
                if denominator_ok
                else {"state": "FAILED", "reasons": ["COMPLETE_PROFILE_DENOMINATOR_REPLAY_FAILED"]}
            )
        elif name == "lineage":
            item = (
                {"state": "PASSED", "reasons": []}
                if lineage_ok
                else {
                    "state": "FAILED",
                    "reasons": ["EXACT_F06_F07_F10_F11_F13_F14_F16_REPLAY_FAILED"],
                }
            )
        state = item.get("state")
        reasons = item.get("reasons")
        if state not in {"PASSED", "FAILED", "UNPERFORMED"} or not isinstance(
            reasons, (tuple, list)
        ):
            output[name] = {"state": "FAILED", "reasons": ["VERIFIER_CHECK_MALFORMED"]}
        else:
            normalized = sorted(set(item for item in reasons if isinstance(item, str)))
            if state == "PASSED" and normalized:
                output[name] = {"state": "FAILED", "reasons": ["VERIFIER_CHECK_MALFORMED"]}
            elif state == "FAILED" and not normalized:
                output[name] = {
                    "state": "FAILED",
                    "reasons": ["VERIFIER_CHECK_FAILED_WITHOUT_REASON"],
                }
            else:
                output[name] = {"state": state, "reasons": normalized}
    return output


def _failed_verification(reason: str) -> TimestampVerificationResult:
    checks = {name: {"state": "UNPERFORMED", "reasons": []} for name in CHECK_NAMES}
    checks["status"] = {"state": "FAILED", "reasons": [reason]}
    identity = {
        "status": None,
        "imprint_algorithm": None,
        "imprint_hex": None,
        "nonce_hex": None,
        "policy_oid": None,
        "serial_hex": None,
        "gen_time_utc": None,
        "accuracy": {"seconds": None, "millis": None, "micros": None},
        "signer_fingerprint": None,
        "issuer": None,
        "certificate_serial_hex": None,
        "ess_binding": None,
    }
    return TimestampVerificationResult("FAILED", identity, (), checks, (reason,))


def _available_fact(
    value: int,
    evidence_ids: tuple[str, ...],
    records: tuple[SettlementEvidence, ...],
    fact_key: str,
) -> dict[str, Any]:
    digest = _selected_evidence_digest(evidence_ids)
    chosen = sorted(records, key=lambda item: (item.record_id, item.evidence_digest))
    sources = [item for item in chosen if getattr(item, fact_key) == value]
    selected = sources[0] if sources else (chosen[0] if chosen else None)
    if selected is None:
        return _unavailable_fact("MISSING", "T10_SELECTED_EVIDENCE_NOT_RETAINED", ())
    provenance = dict(selected.provenance)
    revision = next(
        (
            provenance[key]
            for key in ("source_revision_id", "revision_id", "fixture_revision_id")
            if isinstance(provenance.get(key), str)
        ),
        None,
    )
    reasons = []
    if revision is None:
        reasons.append("SOURCE_REVISION_ID_NOT_SUPPLIED")
    return {
        "value": value,
        "state": "AVAILABLE",
        "reasons": sorted(reasons),
        "selected_evidence_digest": digest,
        "source_record_id": selected.record_id,
        "source_assertion_ids": sorted(
            {assertion for item in chosen for assertion in item.source_assertion_ids}
        ),
        "source_revision_id": revision,
        "published_at_utc": _optional_exact_utc(selected.published_at_utc),
        "observed_at_utc": _optional_exact_utc(selected.observed_at_utc),
        "retrieved_at_utc": _optional_exact_utc(selected.retrieved_at_utc),
    }


def _unavailable_fact(
    state: str, reason: str, records: tuple[SettlementEvidence, ...]
) -> dict[str, Any]:
    chosen = sorted(records, key=lambda item: (item.record_id, item.evidence_digest))
    return {
        "value": None,
        "state": state,
        "reasons": [reason],
        "selected_evidence_digest": None,
        "source_record_id": chosen[0].record_id if len(chosen) == 1 else None,
        "source_assertion_ids": sorted(
            {assertion for item in chosen for assertion in item.source_assertion_ids}
        ),
        "source_revision_id": None,
        "published_at_utc": None,
        "observed_at_utc": None,
        "retrieved_at_utc": None,
    }


def _family_state(
    groups: tuple[Any, ...],
    required_fact_keys: tuple[str, ...],
    *,
    derivation_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected, conflict, related = _fact_group(groups, required_fact_keys)
    if selected is not None:
        state = "AVAILABLE"
        selected_digests = sorted({record.evidence_digest for record in selected.records})
        reasons: list[str] = []
    elif conflict:
        state = "CONFLICTING"
        selected_digests = sorted(
            {record.evidence_digest for group in related for record in group.records}
        )
        reasons = ["T10_SOURCE_HIERARCHY_CONFLICT"]
    else:
        state = "MISSING"
        selected_digests = []
        reasons = ["T10_REQUIRED_COHERENT_FACT_SET_NOT_AVAILABLE"]
    return {
        "state": state,
        "required_fact_keys": list(required_fact_keys),
        "selected_evidence_digests": selected_digests,
        "derivation_rule": derivation_rule,
        "reasons": reasons,
    }


def _records_for(
    evidence_ids: tuple[str, ...], evidence: tuple[SettlementEvidence, ...]
) -> tuple[SettlementEvidence, ...]:
    selected = set(evidence_ids)
    return tuple(item for item in evidence if item.evidence_id in selected)


def _selected_evidence_digest(evidence_ids: tuple[str, ...]) -> str:
    return digest_bytes(canonical_bytes({"evidence_ids": sorted(set(evidence_ids))}))


def _t10_rule_reference() -> dict[str, Any]:
    return _reference(
        SETTLEMENT_RULES_NAME,
        SETTLEMENT_RULES_VERSION,
        _module_digest("matchvet.t10"),
    )


def _t12_rule_reference() -> dict[str, Any]:
    return _reference(
        "matchvet.t12.derive_second_half_goals",
        SECOND_HALF_GOAL_MODEL_VERSION,
        _module_digest("matchvet.t12"),
    )


def _reference(identifier: str, version: str, digest: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "version": version,
        "digest": digest,
        "state": "PRESENT",
        "reasons": [],
    }


def _module_digest(module_name: str = "matchvet.cb01_trust") -> str:
    import importlib

    module = importlib.import_module(module_name)
    return digest_bytes(Path(cast(str, module.__file__)).read_bytes())


def _present_digest(reference: dict[str, Any]) -> str:
    if reference["state"] != "PRESENT" or not isinstance(reference["digest"], str):
        raise CB01Error("Required live F16/F14 lineage reference is unavailable.")
    return reference["digest"]


def _optional_exact_utc(value: str | None) -> str | None:
    return normalize_utc(value) if value is not None else None


def _has_media_base(media_type: str, expected: str) -> bool:
    return media_type == expected or media_type.startswith(expected + ";")


def _tuf_document_version(content: bytes, role: str) -> int:
    try:
        document = json.loads(content)
        signed = document["signed"]
        version = signed["version"]
        metadata_type = signed["_type"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CB01Error(f"Retained Sigstore TUF {role} metadata is malformed.") from error
    if metadata_type != role or type(version) is not int or version < 1:
        raise CB01Error(f"Retained Sigstore TUF {role} identity is malformed.")
    return version


def _media_with_parameters(base: str, parameters: dict[str, str]) -> str:
    return base + "".join(f";{key}={parameters[key]}" for key in sorted(parameters))


def _media_parameters(media_type: str, base: str) -> dict[str, str]:
    if not _has_media_base(media_type, base):
        raise CB01Error("Protected raw artifact has an unexpected media type.")
    values: dict[str, str] = {}
    for item in media_type[len(base) :].split(";")[1:]:
        key, separator, value = item.partition("=")
        if not separator or not key or key in values or not value:
            raise CB01Error("Protected raw artifact media parameters are malformed.")
        values[key] = value
    return values


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded, altchars=b"-_", validate=True)


def _decode_trust_state(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_unb64(value))
        if not isinstance(parsed, dict) or canonical_bytes(parsed) != _unb64(value):
            raise ValueError("trust-state metadata is noncanonical")
        return trust_state_schema(parsed)
    except (ValueError, TypeError, json.JSONDecodeError, CB01TrustError) as error:
        raise CB01Error(
            "RFC3161 request does not retain exact authenticated TUF identity."
        ) from error


def _bare_digest(value: str) -> str:
    digest = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise CB01Error("F06 digest does not use the exact supported namespace.")
    return digest


def _is_positive_hex_nonce(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]+", value)) and int(value, 16) > 0

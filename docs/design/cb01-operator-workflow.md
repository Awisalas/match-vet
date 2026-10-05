# Enroll a fixture with CB01

Use `BootstrapRepository` to enroll one exact F06 INCLUDED fixture for one exact F07 cutoff and F14 Profile. The repository prepares the complete enabled-preference denominator and sends one Sigstore RFC3161 request for its canonical batch.

## Enroll a fixture

Pass the exact retained IDs from F06, F07, and F14. Pass the exact F16 manifest digest when one is available. Use `None` when F16 is missing so the denominator can still be retained as incomplete.

```python
from pathlib import Path

from matchvet.cb01 import BatchResult, BootstrapRepository, FixtureEnrollmentInput
from matchvet.store import open_store


def enroll_fixture(
    database_path: Path,
    private_root: Path,
    freeze_id: str,
    membership_id: str,
    cutoff_id: str,
    profile_digest: str,
    f16_manifest_digest: str | None,
) -> BatchResult:
    request = FixtureEnrollmentInput(
        freeze_id=freeze_id,
        membership_id=membership_id,
        cutoff_id=cutoff_id,
        profile_digest=profile_digest,
        f16_manifest_digest=f16_manifest_digest,
    )
    with open_store(database_path, private_root=private_root) as store:
        result = BootstrapRepository(store).enroll_fixture(request)
        print(result.state, result.batch_digest, result.attempt_digest, result.publication_digest)
        return result
```

`BatchResult` returns the batch, attempt, verification, publication, failure, and row identities. Save those exact digests with the operator's run notes. A live result has a publication digest. An incomplete result retains its reasons and expected rows.

## Resume an interrupted batch

Reopen the same private store and name the exact batch and attempt digests. `resume` replays retained request, response, trust, and source artifacts. It does not send another request unless you pass `retry_failed=True` after reviewing a durable failed attempt.

```python
from pathlib import Path

from matchvet.cb01 import BatchResult, BootstrapRepository
from matchvet.store import open_store


def resume_fixture(
    database_path: Path,
    private_root: Path,
    batch_digest: str,
    attempt_digest: str,
    *,
    retry_failed: bool = False,
) -> BatchResult:
    with open_store(database_path, private_root=private_root) as store:
        result = BootstrapRepository(store).resume(
            batch_digest,
            attempt_digest,
            retry_failed=retry_failed,
        )
        print(result.state, result.batch_digest, result.attempt_digest, result.publication_digest)
        return result
```

If the process stopped after retaining a request but before publishing its `TimestampAttempt`, call `enroll_fixture` again with the same exact input. The repository adopts the retained request. An explicit retry creates a new attempt and nonce. CB01 permits one normal request and one explicit retry per exact batch.

## Inspect the full denominator

Name the exact F06 freeze, exact F14 Profile, and the publication digests you want to inspect. The result includes each frozen membership multiplied by each enabled preference. F06 exclusions and unattempted included fixtures remain visible.

```python
from pathlib import Path

from matchvet.cb01 import BootstrapRepository, DenominatorView
from matchvet.store import open_store


def inspect_freeze(
    database_path: Path,
    private_root: Path,
    freeze_digest: str,
    profile_digest: str,
    publication_digests: tuple[str, ...],
) -> DenominatorView:
    with open_store(database_path, private_root=private_root) as store:
        view = BootstrapRepository(store).inspect_denominator(
            freeze_digest,
            profile_digest,
            publication_digests,
        )
        return view
```

## Attach an exact F19 settlement

After a row is `ENROLLED_LIVE`, pass its exact EnrollmentRecord digest and an exact retained F19 settlement digest. Pass the prior CB01 attachment digest when attaching an F19 correction.

```python
from pathlib import Path

from matchvet.cb01 import BootstrapRepository
from matchvet.store import open_store


def attach_settlement(
    database_path: Path,
    private_root: Path,
    enrollment_digest: str,
    settlement_digest: str,
    *,
    exact_fact_evidence: tuple[str, ...] | None = None,
    predecessor_digest: str | None = None,
) -> tuple[str, str]:
    with open_store(database_path, private_root=private_root) as store:
        return BootstrapRepository(store).attach_outcome(
            enrollment_digest,
            settlement_digest,
            exact_fact_evidence=exact_fact_evidence,
            predecessor_digest=predecessor_digest,
        )
```

The returned digests identify the append-only `OutcomeAttachment` and its `OutcomeFactAttachment`. CB01 preserves the exact F19 state and separately records available or missing T10 facts. A settlement grade does not fill missing result facts. To add supplemental facts, pass their exact same-fixture T10 evidence digests. CB01 always resolves the complete F19 evidence snapshot and rejects a selection that omits any of its records.

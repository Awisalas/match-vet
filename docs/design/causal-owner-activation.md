# Private causal owner contract

Issue #87 implements mechanics under ADR 0005. Nothing installs production
authority or authorizes source use. The immutable V1 profile remains unchanged.

## Envelope fixed before implementation

Every owner record is canonical UTF-8 JSON using sorted keys, compact separators,
unescaped Unicode, no duplicate keys or non-finite numbers. The envelope has
exactly `signed` and `signature`. `signature` is lowercase hexadecimal Ed25519,
verified by maintained OpenSSL `pkeyutl -verify -rawin`. The signed message is
`matchvet-causal-owner-v1` followed by one NUL byte and canonical `signed` JSON.
The approval identity is SHA-256 of the exact complete signed envelope bytes.
The owner identity is SHA-256 of its Ed25519 SubjectPublicKeyInfo DER.

The `signed` object contains exactly:

| Field | Meaning |
| --- | --- |
| `domain`, `schema_version`, `algorithm`, `action` | `matchvet-causal-owner-v1`, integer 1, `Ed25519`, and `activate`, `admit`, `withdraw`, or `reconcile` |
| `owner`, `deployment`, `catalog`, `history` | Installed key digest, explicit deployment identity, resolved SQLite path, independent authoritative history identity |
| `sequence`, `predecessor` | Positive contiguous integer; prior exact envelope SHA-256, null only for sequence 1 activation |
| `purpose`, `issue` | `RESEARCH_ONLY`, integer 70 |
| `profile_digest`, `profile` | Exact immutable V1 digest and complete parsed V1 profile, including operator, endpoint, policy revision/digest/OID, signer, anchor, bootstrap10, initial TrustedRoot, reviewed floors, UNSMEARED_UTC, accepted premises, historical assurance and false current-revocation flag |
| `accepted_premises` | Exactly `operator_policy_compliance`, `uncompromised_authority`, `unsmeared_utc`, all JSON true; explicit conditional acceptance of the operator's published UTC/accuracy policy and uncompromised authority |
| `not_before`, `not_after` | Exact approval UTC interval, inclusive endpoints; strictly increasing |
| `bundle`, `floors` | Full exact closure as lowercase hex, including sequential roots11 onward, timestamp, snapshot, targets and TrustedRoot; four exact authenticated role/version/hash triples |
| `adverse` | Null or exact `effective_from`, `published_at`, `observed_at`; unknown effective boundary is null and invalidates all affected events |

Activation is first and unique in a history. Admission changes only bundle/floors
after existing TUF signatures/references/hashes/pins verify. Floors never decrease;
equal versions require equal hashes. TrustedRoot must retain the initial exact pin.
Already admitted root rotations remain an exact byte prefix of every later chain.
Approval bounds and every profile/policy/premise identity remain fixed. Withdrawal
retains the bundle and bounds, records adverse evidence separately from observation
and publication, and permanently prevents new work in that history. Reconciliation
retains the preceding state exactly. It cannot erase adverse evidence or restore
request/receipt capabilities. All records are immutable numbered files
`00000000000000000001.json` onward. No record overwrite is an administrative update.

## Independently trusted installation and current continuity

The private loader reads only `sys.base_prefix/etc/matchvet/causal-owner-v1.json`.
There is no environment override, caller configuration, approval argument or
catalog discovery. This owner-installed canonical file contains exactly
`verification_key` as Ed25519 SPKI DER hex, `deployment`, `catalog`, `history`,
`records` as an absolute directory, and `checkpoint_socket` as an absolute path.
It must be owned by the current trusted OS user and not group/world writable.
The installation is part of the trusted code/kernel/configuration premise.

Each load sends a fresh 256-bit nonce in one newline-terminated canonical JSON
request to that Unix socket. The request contains `nonce`, `deployment`, `catalog`
and `history`. The service responds with one canonical signed envelope using the
same scheme/key. Its signed fields are exactly `domain`, `schema_version`,
`algorithm`, `action=checkpoint`, `owner`, `deployment`, `catalog`, `history`,
`nonce`, `sequence`, `head`, `floors`, `continuity=RECONCILED`. The loader requires
the complete local authenticated prefix to equal that independent head and floors.
No saved response is consulted as current authority. Missing, stale, forked,
conflicting, incomplete or uncertain state refuses. The socket exchange is bounded.

The service and its authoritative sequence/head/floors must reside outside both
Store and activation-history backup rollback domains. This is an external owner
prerequisite, not a claim that path separation detects all-copy rollback. The service
must refuse `RECONCILED` unless independent continuity is established, including
Store restore reconciliation. A restored history must recover every signed record
through that independently established head and append owner-signed `reconcile`
before the service attests reconciliation. Restoring all local files or presenting
old signed checkpoints cannot substitute for this fresh external assertion.

## Receipt retention and checks

Approval evidence schema 2 retains exact owner-record envelopes, exact checkpoint
and verification-key bytes, with an explicit `approval_digest`. The active record's envelope digest is the approval
identity. These are protected immutable evidence in the existing manifest format;
no Store/artifact representation change or SQLite migration is needed. Legacy
approval evidence keeps its original reader/bytes. Schema 2 signatures and lineage
can be inspected offline using the retained key, but that key cannot grant present
authority. Present qualification requires an independently installed matching owner
and original history as an exact prefix of the current reconciled history.

Dispatch reloads authority immediately before emission. Receipt admission reloads
at the protected insertion seam after evidence staging. A changed cached approval,
withdrawal or uncertain continuity terminates the occupied slot. The entire signed
event interval must fit original approval, authority, certificates and admitted
metadata bounds; expiry is exclusive. Later metadata never replaces retained
receipt evidence. Present qualification enforces authenticated adverse boundaries;
historical inspection remains immutable even when current authority is unavailable.
No mutable latest fetch, retry, fallback, backfill or restart capability is added.
Separate #86 real-source authorization remains mandatory.

# Design synthesis

Base: candidate-snapshot.md. Graft: candidate-filesystem.md lexical private fresh-operation authority.

Cross-judge gpt-6-sol scores indexed 12/12 and filesystem 11/12 against arena-rubric.md.
Root agrees indexed storage is easier to maintain: existing canonical bytes, immutable
indexes, inspection, backup and recovery already cover the second receipt object.
Filesystem adds an independent parser, path contract, durability and backup owner.

Both candidates pass shallow-module, information-leakage, temporal-decomposition and
pass-through-method screens when authority remains behind one seal/replay owner. Reject
filesystem public request shape exposing caller cutoff/policy/profile duplication;
derive these from exact F16 graph inside the existing settled owner. Keep seal_completed,
replay and replay_for_matchweek, plus the already scoped shared preselection gate.

Choose stable UUIDv5 logical/role namespaces with strict reader mapping. The stronger
UUIDv8 global reservation is not required to prevent qualification: a forged different
Matchweek can occupy a malformed slot but cannot satisfy replay. Accept permanent false
refusal from that malformed slot, matching the requested safety bias. Do not claim the
generic guard prevents all invalid-slot poisoning. No production slot previously exists.

Cross-judge finding acted on: structured StoreTransaction.record_snapshot_manifest must
share the protected-role guard and private live authorization, not only ArtifactStore.
Raw execute/private Python remain within trusted repository implementation; this is an
application-path proof rather than cryptographic provenance against privileged writers.

Preserve full graph replay, consume-before-attempt, Store/PID/operation lifetime checks,
no idempotent capability issuance, no orphan adoption and explicit trusted UTC bound.
Object and directory durability includes previously existing paths. The prototype's
postcommit extra sync barrier conservatively completes graph proof before observation;
production should sync graph and protocol objects before the selection commit.

Verification: scratch prototype initially recorded25 cases; refinement rejects alternate
proposals explicitly and validates wrong-domain generic bytes. Final36 named cases pass.
Proof limitations: synthetic graph, fixed-slot modeled guard, no hardware power-loss or
live clock-accuracy claim. Original failed storage proof remains valid and unchanged.

## Final refinement

The earlier 36/37-case checkpoints above are historical outputs, not the final gate.
The final script uses the actual documented UUIDv5 role formulas and synchronizes every
protocol file and its ancestor directories before the selection/receipt catalog commit;
the earlier extra postcommit barrier is gone. Store-scoped nonreentrant ownership
replaces ambient authorization. Commit exceptions permit only read-only reconciliation
of a surviving receipt, with publication attempt counts proving no retry.

The refined 45-case checkpoint adds these four adversarial behaviors. Two final cases
explicitly prove zero publication for a never-selected candidate at T and an orphan
selection after T, bringing the final proof to 47 cases. See `interrogation.md` for the
non-green instrumentation history and closure. The root rerun and checks are recorded
in the final outputs and append-only trail. All full-F16, hardware and UTC-accuracy
limitations remain unchanged.

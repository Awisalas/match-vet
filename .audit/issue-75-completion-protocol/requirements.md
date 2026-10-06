# Issue #75 protocol investigation

The exact logical-Matchweek selection commit must durably finish before common T.
A later receipt may prove this earlier fact. It must not create a new selection or
change freeze/policy/profile/F16 lineage. Missing or ambiguous completion fails closed
forever for that logical Matchweek. No receipt may be reconstructed from disk on restart.

Candidate: atomic selection commit, then repository clock sample, then a private
one-use in-memory capability if the sample is strictly before T. Only that live
operation can emit a protected receipt, even if receipt publication crosses T.
No public token, serialization, deserialization, persisted token, or backfill API.
The receipt binds logical identity, exact selection, common T and policy, protocol.

Attack crashes at every publication boundary; pauses; competition; reopening in
same/new process; token duplication/replay; clock steps; WAL/journal durability;
receipt corruption/deletion; orphan/missing/corrupt graph; equality; alternate inputs.
Compare ordinary row, precommit timestamp, safety margin, filesystem marker,
external witness, and cleaner local protocol. Explain all trust assumptions.

Only scratch stores/files and synthetic data. No production code, #76, live stores,
fixture/network acquisition, or TSA. Official SQLite/Python docs and GitHub issue
reads/authorized design/acceptance updates are allowed. Preserve prior proof bytes.

Outputs: traced grounding, two distinct design candidates and synthesis, primary
research, throwaway isolated proof script and HTML state demo, adversarial review,
updated design/ADR/#75 if sound, committed proof records including previous evidence.

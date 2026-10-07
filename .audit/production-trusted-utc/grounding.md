# Clock grounding

MatchweekResearchRepository owns clocks, admission and completion; Store owns durability and private authority, not UTC. F11–F16 constructors propagate a provider to repository gates. ArtifactStore guards prospective publication before object/catalog work and after commit.

Sources: src/matchvet/matchweek_research.py:1,41,109,137,257,293,504,552,612; src/matchvet/store.py:4377,4708,4771; src/matchvet/artifacts.py:551,705; docs/matchweek-research.md:59.

Current TrustedUTCClock.observe must return an aware UTC bound >= actual UTC at function return, including suspension, rollback and error. Default raises. Repository rejects non-TRUSTED or decreasing bounds, requires u < T. Gates alone grant no receipt authority. A successful fresh selection commit, followed by valid observation, grants one live receipt attempt. Receipt persistence may finish later; restart never recreates missing receipts. Exact selected replay needs no clock.

Completion v1 has exactly one selection artifact ref and u as created_at_utc. Source/confidence are discarded. Richer provenance needs completion reader/version v2 and private binding update, preserving v1 bytes and stable selection/receipt identities. Existing generic artifacts/manifests suffice; no migration is inherently necessary.

Research warning: authenticated server time bounds server processing, not client return. A BOOTTIME anchor needs a documented lower-rate bound on elapsed counter plus a bound on final-sample-to-return delay. A causal postcommit RFC3161 token proves an earlier commit bound independent of response delay but is not a drop-in actual-now clock. Do not silently alter this distinction or weaken the existing clock contract.

Task stops at researched architecture and isolated proof. No production code, live store, live Matchweek acquisition/rebuild, or #70 fitting. If no mechanism satisfies the contract, report that result instead of asserting trust.

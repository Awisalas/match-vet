# Issue #75 spec review

Baseline: `5c70bb2`. Reviewed the staged diff for `artifacts.py`, `store.py`,
`matchweek_research.py`, `research_identity.py`, and the two new test files against
the accepted completion protocol and the user requirements. No correctness blocker
or scope expansion found.

- Fresh selection exceptions cannot reach completion acknowledgement. The postcommit
  observation follows the protected publisher's successful return; existing selections
  use replay. Evidence: `src/matchvet/matchweek_research.py:246`, `:271`, `:275`.
- Receipt authority is consumed before verification or staging. Store lifetime, exact
  operation, PID, and thread checks constrain its use; copy and serialization refuse.
  Evidence: `src/matchvet/store.py:4649`, `:4662`, `:4673`.
- Receipt publication exceptions permit only indexed read-only replay. Replay requires
  both deterministic mappings and validates the exact role manifests and complete graph.
  There is no public receipt minting or recovery publication method. Evidence:
  `src/matchvet/matchweek_research.py:280`, `:326`, `:342`, `:356`.
- Generic publication and structured insertion guard both reserved roles before ordinary
  publication. The private insertion refuses an occupied slot. Evidence:
  `src/matchvet/artifacts.py:598`; `src/matchvet/store.py:4735`, `:4894`.
- Complete graph admission delegates exact lineage and INCLUDED membership coverage to
  existing F16 replay, then requires the corrected rule, whole exact F07 boundary,
  one common cutoff, and one F11 evidence set. Verified artifact references are retained
  in the selection. Evidence: `src/matchvet/matchweek_research.py:159`;
  `src/matchvet/f16.py:244`, `:280`, `:295`.
- Clock confidence is explicit; the default provider refuses qualification and cutoff
  equality fails. WAL/FULL is checked and graph files plus containing directories are
  synced, including reused paths. Evidence: `src/matchvet/matchweek_research.py:137`,
  `:153`; `src/matchvet/store.py:4380`; `src/matchvet/artifacts.py:919`.
- The stable logical identity helper matches the accepted UUID namespace strings.
  Existing SnapshotManifest canonical serialization and verification logic are unchanged.
  Evidence: `src/matchvet/research_identity.py`; staged `artifacts.py` diff.

These conclusions come from source tracing. This reviewer ran no tests, opened no live
stores, made no network calls, and established no operational clock or hardware
durability proof. Root verification results are separate evidence.

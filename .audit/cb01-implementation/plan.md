# CB01 implementation plan

- [x] Ground: trace the frozen contract, Store, ArtifactStore, F06/F07, F10/F11/F13/F14/F16, and F19/T10/T12 boundaries.
- [x] Sketch: compare structurally distinct designs, screen red flags, and select one public repository seam.
- [x] Agree: use the contract's pre-agreed BootstrapRepository test seam; no design checkpoint was requested.
- [x] Implement: add canonical v1 artifacts, trust refresh/witness verification, exact recovery, publication, and outcome replay.
- [x] Scrap: checked for repeated structural workarounds; none required a contract or repository-seam redesign.
- [x] Verify: run focused and affected checks from the acceptance list; prove the key chronology/recovery safety fact.
- [x] Review: inspect blast radius, reconcile the decision log, and review the implementation and staged diff.
- [x] Release: commit and push the verified patch, close #72, and confirm #70 remains open with F17 still blocked.

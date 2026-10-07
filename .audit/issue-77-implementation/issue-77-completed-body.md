## Parent

Part of #73: Correct F07 and downstream evidence freeze to one Matchweek-wide cutoff.

## What to build

Corrected CB01 records qualify only when they belong to the one selected Matchweek information state. The existing full denominator and per-fixture witness contract remain truthful, F19 settlement stays append-only against its exact frozen decision, and corrected chronological evaluation has a successor to #70's released per-match method.

## Scope

- CB01 preparation, enrollment, denominator, trust, and audit adapters (`cb01_sources`, `cb01`, `cb01_trust`).
- Exact F16/F07 lineage required by the #75 selection and #76 writer gates.
- F19 result/correction lineage and chronological evaluation compatibility.
- #70 corrected-cohort chronology in a new successor record; leave released method 0.1.0 untouched.

## Acceptance criteria

- [x] Corrected CB01 preparation requires the selected F16 lineage and one common F07 policy/T for the complete admitted INCLUDED cohort. Mixed identities cannot qualify or be pooled.
- [x] The full INCLUDED membership × enabled-preference denominator stays visible independently of F16 availability, witness success, or whether an attempt was made. Missing lineage, failed witnesses, and unattempted preferences remain unavailable rows rather than disappearing from the cohort.
- [x] Keep fixture batches and the existing strict witness window `T < signed genTime < that fixture's controlling kickoff`. A witness proves committed bytes existed by `genTime`; it does not prove pre-T evidence collection. No later witness permits evidence or decision refresh.
- [x] Preserve old `cb01.py` and `cb01_trust.py` software identities and exact reconstruction, or dispatch old identities explicitly and pass historical replay tests. Offline trust tests use already-retained deterministic responses only.
- [x] F19 settlement and correction append to the exact selected manifest/decision lineage; outcomes and post-cutoff evidence cannot enter a frozen recommendation input.
- [x] Publish a corrected-policy chronology successor for #70 with one shared origin, the selected-state/policy identities, and separate legacy/corrected cohorts. Do not edit method 0.1.0 or choose unresolved numerical derivation profiles.
- [x] Focused CB01, F19, denominator, chronology, old-token software identity, and offline replay tests pass; Ruff for changed Python and `git diff --check` pass.

## Blocked by

- #76 — CB01 and evaluation can bind the corrected F07 boundary only after F11–F16 enforce the selected Matchweek state.

Use isolated stores and deterministic offline inputs/retained witness fixtures. Do not open or modify either live SQLite store, acquire current fixtures or network data, publish live F artifacts, or request a new Sigstore/RFC3161 timestamp. Do not change old CB01 bytes or rewrite old receipts, F19 history, #70 v0.1.0, historical issues, or `.audit` evidence.

Implemented and pushed to main in f528e31425d54df6ca6ee12d2480f7031838f604.

Corrected CB01 preparation, cohort evaluation and F19 settlement now require the exact selected Matchweek lineage. The full INCLUDED memberships × enabled preferences denominator remains independent of research availability, witnesses and attempts. Corrections stay append-only; explicitly selected outcomes cannot refresh frozen recommendation inputs. Chronology 0.2.0 keeps corrected and legacy cohorts separate and leaves #70 numerical profiles unresolved.

Validation passed using isolated temporary stores and deterministic retained/offline fixtures: 47 focused pytest cases plus the isolated F19 outcome integration, 11 affected #75/#76 regressions and 4 historical CB01/F19 regressions. Archived pre-77 software reconstructed 53 retained artifacts and two enrollment records exactly, with publication forbidden. cb01.py, cb01_trust.py and released method 0.1.0 remain byte-identical. Strict mypy on all 12 changed Python files, Ruff, formatting and final staged/unstaged diff checks passed. Proofs and review are retained under .audit/issue-77-implementation/.

All acceptance criteria are complete. #73 stays open. #78 may become unblocked through its retained native dependency; it has not been started. No live stores, fixture acquisition or live timestamp requests were used.

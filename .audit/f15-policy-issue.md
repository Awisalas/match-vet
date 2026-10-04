## Objective
Bind the exact T15 Selection Policy Version into the F15 AnalyzeMatchweek request and T04 identity before F16.

## Acceptance criteria
- Add an explicit `PolicyVersion` to `AnalyzeMatchweekRequest`.
- Validate/normalize through the existing T15 contract and require `RESEARCH_ONLY`.
- Bind exact policy version and digest into `RunInputContract`; changed policy refuses resume.
- Keep unresolved research-only thresholds explicit; do not invent production thresholds. Downstream policy evaluation remains fail-closed.
- Preserve F15/F13/T04 behavior, add no migration, and do not implement F16.

## Verification
Focused F15/T15/T04 tests, Ruff, and mypy. Close only when acceptance passes.

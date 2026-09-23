# Research-only release qualification

Status: NOT QUALIFIED. This record is being completed against issue #36. It does not grant Production Promotion.

## Scope

T19 checks whether the current MatchVet software can operate as a `RESEARCH_ONLY` system on the supported Termux device. The seven-league corpus is a self-authored structural equivalent licensed CC0-1.0. It checks software contracts, not real-world predictive reliability.

The replay covers Premier League, Serie A, La Liga, Bundesliga, Ligue 1, Liga Portugal, and Belgian Pro League. It exercises approved-source fallback, conflicting context, unknown weather, missing corners, a post-cutoff withdrawal, 37 preference results and grades per Target Match, reports, audits, export, backup, restore, and chronological evaluation.

## Release gate

Run `scripts/qualify-research-release.sh OUTPUT_DIR` from a clean checkout with the locked `.venv`. The output directory must be new and outside the repository. `qualification.json` is the authoritative gate result; `gates.tsv` and `logs/` retain exact commands and failure output.

The checked commit, full results, resource observations, reproducibility digests, and recovery findings will be recorded here after the final run. A missing or failed gate means `NOT QUALIFIED`.

## Known limits

- The self-authored corpus is not observed league data. No prediction-performance or Production Promotion conclusion follows from passing its replay.
- Sparse history leaves calibration unavailable in every recorded league. The chronological framework runs with an explicit target exclusion and an `INCONCLUSIVE` policy result.
- Live source availability and third-party raw-data redistribution are not established by the offline replay. The corpus and export omit rights-restricted raw material.
- Termux is a rolling distribution. A clean offline native rebuild requires the original archives for every pinned package, not reconstructed packages with matching version strings.

Production Promotion has NOT occurred. T20/#37 remains separate statistical work.

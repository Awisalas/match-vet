# Research-only release qualification

Status: **QUALIFIED_RESEARCH_ONLY** for software commit `45b8876a170467c0e7eec0ed229b7043ae631a6b` on 2026-09-23. The [machine-readable result](research-only-release-qualification.json) has digest `4584dfcde8c91adb778d15754cb8e13f204a5ff90f9a43355911959d1c20b24b` and no failure reasons. This is a software qualification under [issue #36](https://github.com/Awisalas/match-vet/issues/36), not a statistical or production-policy decision. Production Promotion has **NOT** occurred.

## What was qualified

The replay ran the T01–T18 contracts from fixture/history ingestion and Matchweek freeze through contextual and workload/weather evidence, Evidence State, grading, FT/half/corner models, calibration, preference vetting, report/audit publication, export, backup, restore, and chronological evaluation. It used a self-authored CC0-1.0 structural corpus; no third-party raw rows are redistributed. Corpus SHA-256: `ca2b0a450e03158567e89c4eec1dd61d2110b72786afb7a7ddb26812a9837241`.

The seven targets span Premier League, Serie A, La Liga, Bundesliga, Ligue 1, Liga Portugal, and Belgian Pro League. Each produced all 37 preference-vetting and settlement/audit contracts: 259 preference results and 259 grades. Settlement outcomes were 86 WIN, 116 LOSS, 8 PUSH, and 49 VOID; 12 missing-corner cases were VOID rather than inferred. The replay exercised one approved-source fallback, one contextual conflict, two `UNKNOWN` weather cases, one withdrawn fixture, and one post-cutoff appendix. It recorded zero silent missing-data inferences, zero prohibited market keys, and zero unspecified publication identities. All 259 preferences remained `REJECT`; reports and audits contained no production decision or confidence language.

Model-family results were 21 `AVAILABLE` and 7 `MODEL_UNAVAILABLE`. All seven calibration bundles were `MODEL_UNAVAILABLE`; no fallback probability was invented. Chronological evaluation reached `EVALUATED_RESEARCH_ONLY` with an `INCONCLUSIVE` policy result: seven recorded targets were explicitly excluded for unavailable calibration and one structural framework observation exercised the evaluation path. There is no evaluated real-world performance sample here.

## Checks and evidence

The fixed-commit runner `scripts/qualify-research-release.sh` passed every required gate. Its logs, resource records, native archives, and checksums remain in `/data/data/com.termux/files/home/projects/match-vet-t19-qualification-45b8876/`. The committed JSON is byte-identical to that run's `qualification.json` (file SHA-256 `5003fa509f0766eaa7e6f78dc466f4ad61bd3ab36ebe6963232543d243441d5a`). Environment record SHA-256: `942c3a79cf89d341a3988b3790e1e58f679ba73d2c3a28efb79bd12a12af0cb1`.

| Gate | Result |
| --- | --- |
| Ruff check and format, mypy | PASS |
| Full locked-environment default pytest | PASS: 495 tests |
| Migration/recovery and CLI/report/audit/export/backup/restore suites | PASS |
| Representative failure-injection matrix | PASS |
| Chronological evaluation suite | PASS |
| Exact native-artifact capture and clean offline project rebuild/install | PASS |
| Clean Termux CLI smoke | PASS |
| Standalone seven-league recorded E2E | PASS |
| Independent deterministic replay | PASS |
| Actual-device resource benchmark | PASS |

The second process reproduced the replay digest `ffb680d3e47da3c640ae194b3b4f8db3652a29157153868c71353f70990f66cc`, report digest `1a89ac69c3e55dafb0efd889abd0b2cd9b0d545b160b5fa992259f6620bad334`, audit/restored-audit digest `6e5b0f1453a515f6f59c8e5a2ea2323c529377f60964ed42f064e974995e82e3`, export digest `82f53cc74f6569455e398a153a1d4d0e2f0f7fff13eb4aefeffb10c9f31d3e30`, and evaluation digest `7bfde3b6efd341e80eea51ef56dc5d2b79b9ff20b34d87f13758eb7d9a32867c`. Grade identity matched across replay and restore. Each backup verified and restored independently. Backup database bytes intentionally differ across runs because durable run IDs, timestamps, and measured resources differ.

The failure matrix covered every T04 durable phase boundary; interruption/resume across ingestion, Matchweek, workload/weather, and Evidence State; stale and digest-mismatched checkpoints; missing/corrupt objects and read-only recovery; unmarked audit/export/backup publication; tampered or incomplete backups; incompatible or foreign-key-invalid restore; restore atomicity; insufficient free space; and chronological-evaluation checkpoint integrity. These cases refused or resumed through existing contracts without publishing partial authoritative state.

## Device and offline rebuild

Resource qualification ran on Samsung SM-A266B, Android 16/API 36, Termux 0.118.3 F-Droid, aarch64. Toolchain: Python 3.14.6, uv 0.12.1, Ruff 0.16.1, mypy 1.18.2, SQLite 3.53.4, NumPy 2.4.4, SciPy 1.18.1. `uv.lock`, `environment/termux-packages.lock`, and `pyproject.toml` were hashed in the retained environment record. `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1` were enforced.

| Measurement | Observed | Settled bound |
| --- | ---: | ---: |
| Seven-league replay runtime | 170.86 s | 7,200 s target; 14,400 s hard limit |
| Peak observed memory | 751,738,880 B | 1 GiB target |
| Temporary storage growth | 101,817,116 B | 2 GiB qualification bound |
| Final managed storage | 333,726,027 B | 1.5 GiB cap |
| Minimum free space | 11,548,454,912 B | 3 GiB floor |
| Peak observed process threads (conservative CPU-heavy upper bound) | 2 | 2 CPU-heavy operations |
| Replay network use (offline socket guard) | 0 B | 250 MiB routine cap |

The offline check captured all nine pinned Termux aarch64 archives, verified package/version/architecture/SHA-256 and the Python lock/cache, then rebuilt a clean project clone and virtual environment with `uv sync --offline --locked --no-python-downloads`. It executed the extracted original native tools and passed the offline doctor. The full archive manifest reverified with `sha256sum -c --status`; captured artifacts total 106,894,440 bytes. Exact Ruff 0.16.1 (`ff24fe107d77c05d777949d96523207c894951b6064f398ea399f622d93b54dc`) and uv 0.12.1 (`2c887618d3b3a737de2567a16f9a866bf581e2754d351b36e04e2b80ca6ea503`) came from [official Termux Ruff build run 30600514499](https://github.com/termux/termux-packages/actions/runs/30600514499) and [official Termux uv build run 30681881722](https://github.com/termux/termux-packages/actions/runs/30681881722), with matching official build checksums and installed binary payloads. The archives are retained privately on the device, not redistributed by this repository. This verifies a clean application rebuild on the fixed Termux prefix; it is not a full Android or Termux image reinstall.

## Limits and next decision

- The corpus is synthetic structural data, not observed league matches. Passing proves software composition and recovery, not predictive reliability or profitability.
- Sparse history leaves calibration unavailable in all seven replay targets. Chronology validates framework behavior, but its policy result is `INCONCLUSIVE`; no statistical promotion threshold was invented or passed.
- Live data-source availability, long-run completeness, and rights to redistribute third-party raw captures remain unresolved. Export deliberately omits restricted raw material. Offline replay cannot establish live-feed reliability.
- The exact offline artifacts are device-local. Reproduction elsewhere requires the retained hashes and authoritative package archives, plus a compatible Termux prefix; the rolling mirror alone may no longer provide these versions.

T19 qualifies only the current software as `RESEARCH_ONLY`. #37/T20 may begin as separate statistical/data work after this dependency is closed, but no policy is Production-Promoted and no `PLAY` path is authorized.

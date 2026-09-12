# Termux environment

MatchVet uses the native aarch64 Termux runtime. Do not use a uv-managed Python, pyenv, Conda, proot, Docker, or global pip installation for project dependencies.

## Pinned baseline

The first environment baseline is:

- Termux 0.118.3 from F-Droid on Android 16, API 36
- CPython 3.14.6 from Termux package python 3.14.6-1
- uv 0.12.1 and Ruff 0.16.1 from Termux
- NumPy 2.4.4-1 and SciPy 1.18.1 from Termux packages
- SQLite CLI 3.53.4 and Git 2.55.0 from Termux packages
- Requests 2.34.2, pytest 9.1.1, and mypy 1.18.2 from the locked Python environment
- one OpenBLAS and OpenMP thread per process

Termux is a rolling distribution. Keep the exact native package files outside the repository in a verified recovery bundle. A Python lock alone cannot reproduce native Termux packages after a mirror removes them.

## Native packages

The required exact native package list is recorded in environment/termux-packages.lock. Install those versions from retained package files or a repository that still provides the exact versions. Do not accept a partial Termux upgrade as equivalent to this baseline.

## Python environment

The bootstrap script checks the native package versions, creates a virtual environment with access to Termux system packages, and installs the locked Python dependencies without downloading another interpreter.

    scripts/bootstrap-termux.sh

The script fails on version drift. It does not upgrade or replace Termux packages.

## Capture and verification

The JSON doctor report is the environment record for a run:

    .venv/bin/matchvet doctor --json > matchvet-environment.json

Run `doctor` from the MatchVet repository. The report includes Android, Termux, Python, architecture, kernel, enabled Termux repositories, complete dpkg inventory, exact project package versions, numerical thread limits, the Git commit, and SHA-256 digests for the project environment manifests. Required capture or manifest failures make the preflight fail. It reads a fixed allowlist and never copies arbitrary environment variables, tokens, or credentials.

Retain the report with the matching native package files, Python wheel archive, uv lock, repository commit, and checksums. A clean offline rebuild and restore test remains a release gate before production output.

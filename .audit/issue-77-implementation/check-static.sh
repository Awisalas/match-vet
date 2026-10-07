#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
set -- src/matchvet/cb01_sources.py src/matchvet/f19.py src/matchvet/cb01_evaluation.py src/matchvet/cb01_replay.py tests/test_cb01_repository.py tests/test_f19.py tests/issue77_support.py tests/test_issue77.py tests/test_issue77_history.py .audit/issue-77-implementation/historical-proof.py .audit/issue-77-implementation/run-slate-slice.py .audit/issue-77-implementation/run-retained-focused.py
.venv/bin/mypy --strict "$@" > .audit/issue-77-implementation/mypy-delivery.txt 2>&1
env -u LD_PRELOAD /data/data/com.termux/files/usr/glibc/lib/ld-linux-aarch64.so.1 --library-path /data/data/com.termux/files/usr/glibc/lib .audit/issue-76-implementation/ruff-aarch64-unknown-linux-gnu/ruff check "$@" > .audit/issue-77-implementation/ruff-delivery.txt 2>&1
env -u LD_PRELOAD /data/data/com.termux/files/usr/glibc/lib/ld-linux-aarch64.so.1 --library-path /data/data/com.termux/files/usr/glibc/lib .audit/issue-76-implementation/ruff-aarch64-unknown-linux-gnu/ruff format --check "$@" > .audit/issue-77-implementation/format-delivery.txt 2>&1
git diff --check > .audit/issue-77-implementation/diff-check-delivery.txt 2>&1
git diff --cached --check >> .audit/issue-77-implementation/diff-check-delivery.txt 2>&1
sha256sum src/matchvet/cb01.py src/matchvet/cb01_trust.py docs/product-v2/CANDIDATE-INPUT-METHODOLOGY.md > .audit/issue-77-implementation/historical-sha256-delivery.txt

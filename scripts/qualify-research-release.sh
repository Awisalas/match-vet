#!/data/data/com.termux/files/usr/bin/sh
set -u

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export UV_PYTHON_DOWNLOADS=never

if [ "$#" -ne 1 ]; then
    echo "usage: scripts/qualify-research-release.sh OUTPUT_DIR" >&2
    exit 2
fi

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
qualification_output=$1
if [ -e "$qualification_output" ]; then
    echo "qualification output already exists: $qualification_output" >&2
    exit 2
fi
mkdir -p "$qualification_output/logs"
qualification_output=$(cd "$qualification_output" && pwd)
case "$qualification_output/" in
    "$project_root/"*)
        echo "qualification output must be outside the repository" >&2
        exit 2
        ;;
esac
qualification_results="$qualification_output/gates.tsv"
qualification_tmp=$(mktemp -d)
trap 'rm -rf "$qualification_tmp"' EXIT HUP INT TERM

printf 'gate\tstatus\texit_code\telapsed_seconds\toutput_digest\tcommand\tlog\n' \
    > "$qualification_results"

run_gate() {
    gate_name=$1
    shift
    gate_log="$qualification_output/logs/$gate_name.log"
    gate_started=$(date +%s)
    "$@" > "$gate_log" 2>&1
    gate_exit=$?
    gate_finished=$(date +%s)
    gate_elapsed=$((gate_finished - gate_started))
    gate_digest=$(sha256sum "$gate_log" | awk '{print $1}')
    if [ "$gate_exit" -eq 0 ]; then
        gate_status=PASS
    else
        gate_status=FAIL
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$gate_name" "$gate_status" "$gate_exit" "$gate_elapsed" \
        "$gate_digest" "$*" "$gate_log" \
        >> "$qualification_results"
    return 0
}

git rev-parse HEAD > "$qualification_output/software-commit.txt"
{
    printf 'OPENBLAS_NUM_THREADS=%s\n' "$OPENBLAS_NUM_THREADS"
    printf 'OMP_NUM_THREADS=%s\n' "$OMP_NUM_THREADS"
    printf 'UV_PYTHON_DOWNLOADS=%s\n' "$UV_PYTHON_DOWNLOADS"
    git rev-parse HEAD
    git remote -v
    sha256sum uv.lock environment/termux-packages.lock pyproject.toml
    uname -a
    getprop ro.build.version.release 2>/dev/null || true
    getprop ro.build.version.sdk 2>/dev/null || true
    python --version
    uv --version
    gh --version
    ruff --version
    .venv/bin/mypy --version
    sqlite3 --version
    pkg list-installed
    .venv/bin/matchvet doctor --json
    apt-config dump
} > "$qualification_output/environment.txt" 2>&1

run_gate static_checks sh -c \
    'test -z "$(git status --porcelain --untracked-files=all)" && ruff check . && ruff format --check . && .venv/bin/mypy'
run_gate default_tests .venv/bin/pytest -q
run_gate migrations_recovery .venv/bin/pytest -q tests/test_store.py tests/test_runs.py
run_gate cli_report_audit_export_backup_restore .venv/bin/pytest -q \
    tests/test_cli.py tests/test_t16.py tests/test_t17.py
run_gate failure_injection .venv/bin/pytest -q \
    tests/test_runs.py::test_every_durable_phase_boundary_recovers_without_partial_publication \
    tests/test_artifacts.py::test_missing_and_corrupt_objects_are_rejected_and_reported \
    tests/test_artifacts.py::test_reopening_store_with_missing_artifact_enters_read_only_recovery \
    tests/test_artifacts.py::test_process_crash_after_object_publication_leaves_a_detectable_orphan \
    tests/test_artifacts.py::test_process_crash_after_database_commit_preserves_verifiable_artifact \
    tests/test_ingestion.py::test_t06_runner_resumes_from_t04_checkpoint \
    tests/test_matchweek.py::test_t05_runner_resumes_from_t04_checkpoint_without_recomputing_membership \
    tests/test_workload_weather.py::test_t08_runner_resumes_after_interruption_and_keeps_weather_observed \
    tests/test_t09.py::test_runner_checkpoint_resume_requires_exact_digests \
    tests/test_runs.py::test_valid_resume_reuses_only_completed_digest_matched_work \
    tests/test_runs.py::test_resume_digest_mismatch_preserves_incomplete_run \
    tests/test_t16.py::test_interrupted_audit_publication_stays_invisible_until_marker \
    tests/test_t17.py::test_backup_rejects_corrupt_database_and_resource_floor_before_mutation \
    tests/test_t17.py::test_interrupted_export_leaves_only_unmarked_partial_state \
    tests/test_t17.py::test_interrupted_backup_leaves_only_unmarked_partial_state \
    tests/test_t17.py::test_restore_rejects_tampered_backup_and_leaves_authoritative_state_untouched \
    tests/test_t17.py::test_restore_refuses_existing_target_and_missing_protected_object \
    tests/test_t17.py::test_interrupted_restore_cleans_only_its_activation_files \
    tests/test_t17.py::test_restore_rejects_incompatible_manifest_and_sqlite_foreign_key_failure \
    tests/test_t18.py::test_interrupted_evaluation_resumes_only_with_identical_inputs \
    tests/test_t18.py::test_checkpoint_digest_tamper_is_rejected \
    tests/test_store.py::test_corrupt_database_enters_unreadable_recovery_mode
run_gate chronological_evaluation .venv/bin/pytest -q tests/test_t18.py

recovery_artifacts="$qualification_output/recovery-artifacts"
online_source="$qualification_tmp/online-source"
offline_source="$qualification_tmp/offline-source"
run_gate offline_rebuild_install scripts/capture-offline-rebuild.sh \
    "$recovery_artifacts" "$online_source" "$offline_source"
if [ -f "$recovery_artifacts/artifact-sha256.txt" ]; then
    sha256sum "$recovery_artifacts/artifact-sha256.txt" \
        >> "$qualification_output/environment.txt"
fi
run_gate termux_smoke .venv/bin/python -m matchvet --help

replay_workspace="$qualification_output/replay-workspace"
replay_record="$qualification_output/replay-resource.json"
software_commit=$(cat "$qualification_output/software-commit.txt")
run_gate seven_league_recorded_e2e .venv/bin/python -m matchvet.t19 \
    tests/recorded/t19-seven-league.json "$replay_workspace" "$replay_record" \
    --software-commit "$software_commit"
deterministic_workspace="$qualification_output/deterministic-workspace"
deterministic_record="$qualification_output/deterministic-replay-resource.json"
run_gate deterministic_replay sh -c \
    ".venv/bin/python -m matchvet.t19 tests/recorded/t19-seven-league.json '$deterministic_workspace' '$deterministic_record' --software-commit '$software_commit' && .venv/bin/python scripts/compare-t19-replays.py '$replay_record' '$deterministic_record'"
replay_exit=$(awk -F '\t' '$1 == "seven_league_recorded_e2e" {print $3}' "$qualification_results")
if [ "$replay_exit" = 0 ]; then
    replay_status=PASS
else
    replay_status=FAIL
fi
replay_elapsed=$(awk -F '\t' '$1 == "seven_league_recorded_e2e" {print $4}' "$qualification_results")
if [ -f "$replay_record" ]; then
    replay_digest=$(sha256sum "$replay_record" | awk '{print $1}')
else
    replay_digest=$(sha256sum "$qualification_output/logs/seven_league_recorded_e2e.log" | awk '{print $1}')
fi
printf 'resource_benchmark\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$replay_status" "$replay_exit" "$replay_elapsed" "$replay_digest" \
    'measured by matchvet.t19 recorded replay' \
    "$replay_record" >> "$qualification_results"

qualification_manifest="$qualification_output/qualification.json"
if .venv/bin/python scripts/build-t19-manifest.py \
    "$qualification_results" "$replay_record" "$deterministic_record" \
    "$qualification_output/environment.txt" \
    "$qualification_output/software-commit.txt" \
    "$qualification_manifest"; then
    echo "All T19 software gates passed. Production Promotion has NOT occurred."
    exit 0
fi
echo "T19 qualification failed. See $qualification_manifest and $qualification_results" >&2
exit 1

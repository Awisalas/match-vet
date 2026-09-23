#!/data/data/com.termux/files/usr/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: capture-offline-rebuild.sh RECOVERY_DIR ONLINE_SOURCE OFFLINE_SOURCE" >&2
    exit 2
fi

recovery_dir=$1
online_source=$2
offline_source=$3
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
native_dir="$recovery_dir/native-packages"
uv_cache="$recovery_dir/uv-cache"
native_arch=$(dpkg --print-architecture)
native_sources="$recovery_dir/native-package-sources.tsv"

fetch_termux_build_archive() {
    package=$1
    expected=$2
    case "$package=$expected" in
        ruff=0.16.1)
            build_commit=e753fca15bf69b85903b8b9fa480d09d9af60e46
            build_run=30600514499
            build_artifact=debs-aarch64-e753fca15bf69b85903b8b9fa480d09d9af60e46
            expected_sha256=ff24fe107d77c05d777949d96523207c894951b6064f398ea399f622d93b54dc
            ;;
        uv=0.12.1)
            build_commit=0ea2e6ae2a5ebc7c0c6d3215c659215278210915
            build_run=30681881722
            build_artifact=debs-aarch64-0ea2e6ae2a5ebc7c0c6d3215c659215278210915
            expected_sha256=2c887618d3b3a737de2567a16f9a866bf581e2754d351b36e04e2b80ca6ea503
            ;;
        *)
            echo "$package=$expected: no authoritative archived Termux build is recorded" >&2
            return 1
            ;;
    esac
    artifact_dir="$recovery_dir/native-build-artifacts/$package"
    mkdir -p "$artifact_dir"
    gh run download "$build_run" --repo termux/termux-packages \
        --name "$build_artifact" --dir "$artifact_dir"
    checksum_artifact="checksum-aarch64-$build_commit"
    gh run download "$build_run" --repo termux/termux-packages \
        --name "$checksum_artifact" --dir "$artifact_dir"
    archive_name="${package}_${expected}_${native_arch}.deb"
    tar -xf "$artifact_dir/$build_artifact.tar" -C "$artifact_dir" "debs/$archive_name"
    cp "$artifact_dir/debs/$archive_name" "$native_dir/$archive_name"
    actual_sha256=$(sha256sum "$native_dir/$archive_name" | awk '{print $1}')
    official_sha256=$(awk -v file="debs/$archive_name" \
        '$2 == file {print $1}' "$artifact_dir/$checksum_artifact.txt")
    if [ "$actual_sha256" != "$expected_sha256" ] \
        || [ "$official_sha256" != "$expected_sha256" ]; then
        echo "$package=$expected: authoritative build archive SHA-256 mismatch" >&2
        return 1
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$package" "$expected" "$native_arch" "$actual_sha256" \
        "termux/termux-packages:$build_commit:run-$build_run:$build_artifact" \
        >> "$native_sources"
}

mkdir -p "$recovery_dir" "$native_dir" "$uv_cache" "$online_source"
printf 'package\tversion\tarchitecture\tsha256\tsource\n' > "$native_sources"
git -C "$project_root" bundle create "$recovery_dir/source.bundle" HEAD
git -C "$project_root" archive HEAD | (cd "$online_source" && tar -xf -)
git clone --quiet "$recovery_dir/source.bundle" "$offline_source"

(
    cd "$native_dir"
    while IFS='=' read -r package expected; do
        case "$package" in
            ''|'#'*) continue ;;
        esac
        if ! apt download "$package=$expected"; then
            fetch_termux_build_archive "$package" "$expected"
        else
            archive_name="${package}_${expected}_${native_arch}.deb"
            archive_sha256=$(sha256sum "$archive_name" | awk '{print $1}')
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$package" "$expected" "$native_arch" "$archive_sha256" \
                'configured-Termux-APT' >> "$native_sources"
        fi
    done < "$project_root/environment/termux-packages.lock"
)

while IFS='=' read -r package expected; do
    case "$package" in
        ''|'#'*) continue ;;
    esac
    set -- "$native_dir/${package}_${expected}_"*.deb
    if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
        echo "$package: exactly one installable archive for $expected is required" >&2
        exit 1
    fi
    actual_package=$(dpkg-deb -f "$1" Package)
    actual_version=$(dpkg-deb -f "$1" Version)
    actual_arch=$(dpkg-deb -f "$1" Architecture)
    if [ "$actual_package" != "$package" ] || [ "$actual_version" != "$expected" ] \
        || [ "$actual_arch" != "$native_arch" ]; then
        echo "$package: captured archive metadata does not match the lock" >&2
        exit 1
    fi
done < "$project_root/environment/termux-packages.lock"

native_payload="$online_source/native-payload"
mkdir -p "$native_payload"
for archive in "$native_dir"/*.deb; do
    dpkg-deb --extract "$archive" "$native_payload"
done
native_bin="$native_payload$PREFIX/bin"
for binary in git python3.14 ruff sqlite3 uv; do
    recovered="$native_bin/$binary"
    installed="$PREFIX/bin/$binary"
    if [ ! -f "$recovered" ] || [ ! -f "$installed" ] || ! cmp -s "$recovered" "$installed"; then
        echo "Captured Termux payload does not match the installed $binary binary" >&2
        exit 1
    fi
    "$recovered" --version >/dev/null
done

(
    cd "$online_source"
    export PATH="$native_bin:$PATH"
    UV_CACHE_DIR="$uv_cache" UV_LINK_MODE=copy uv sync --locked --refresh --no-python-downloads
)

(
    cd "$offline_source"
    export PATH="$native_bin:$PATH"
    UV_CACHE_DIR="$uv_cache" UV_LINK_MODE=copy UV_OFFLINE=1 scripts/bootstrap-termux.sh
    .venv/bin/matchvet doctor --json > "$recovery_dir/offline-doctor.json"
    .venv/bin/python -m matchvet --help >/dev/null
)

{
    printf 'OPENBLAS_NUM_THREADS=%s\n' "${OPENBLAS_NUM_THREADS:-UNSET}"
    printf 'OMP_NUM_THREADS=%s\n' "${OMP_NUM_THREADS:-UNSET}"
    printf 'UV_PYTHON_DOWNLOADS=%s\n' "${UV_PYTHON_DOWNLOADS:-UNSET}"
    apt-config dump
} > "$recovery_dir/repository-and-runtime-config.txt"

(
    cd "$recovery_dir"
    find . -type f ! -name artifact-sha256.txt -print0 \
        | sort -z \
        | xargs -0 sha256sum > artifact-sha256.txt
)

captured_bytes=$(du -sb "$recovery_dir" | awk '{print $1}')
if [ "$captured_bytes" -gt 2147483648 ]; then
    echo "Captured bootstrap artifacts exceed the 2 GiB bootstrap session budget." >&2
    exit 1
fi
printf 'captured_artifact_bytes=%s\n' "$captured_bytes"

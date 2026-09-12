#!/data/data/com.termux/files/usr/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
package_lock="$project_root/environment/termux-packages.lock"

if [ "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]; then
  echo "MatchVet requires the native Termux environment." >&2
  exit 1
fi

while IFS='=' read -r package expected; do
  case "$package" in
    ''|'#'*) continue ;;
  esac
  actual=$(dpkg-query -W -f='${Version}' "$package" 2>/dev/null || true)
  if [ "$actual" != "$expected" ]; then
    echo "$package: expected $expected; actual ${actual:-MISSING}" >&2
    exit 1
  fi
done < "$package_lock"

cd "$project_root"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export UV_PYTHON_DOWNLOADS=never

uv venv --python "$PREFIX/bin/python" --system-site-packages --allow-existing
uv sync --locked --no-python-downloads
.venv/bin/matchvet doctor

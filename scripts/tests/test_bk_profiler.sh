#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

source "${REPO_DIR}/scripts/bk_functions.sh"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

FAKE_BIN="${TMP_DIR}/bin"
mkdir -p "${FAKE_BIN}"

cat > "${FAKE_BIN}/fapp" <<'EOF'
#!/bin/bash
set -euo pipefail
mode=""
dir=""
event=""
while [ $# -gt 0 ]; do
  case "$1" in
    -C|-A)
      mode="$1"
      ;;
    -d)
      shift
      dir="$1"
      ;;
    -Hevent=*)
      event="${1#-Hevent=}"
      ;;
  esac
  shift || true
done

if [ "$mode" = "-C" ]; then
  mkdir -p "$dir"
  printf '%s\n' "$event" > "${dir}/event.txt"
  exit 0
fi

if [ "$mode" = "-A" ]; then
  printf 'summary:%s\n' "$dir"
  exit 0
fi

exit 1
EOF

cat > "${FAKE_BIN}/fapppx" <<'EOF'
#!/bin/bash
set -euo pipefail
dir=""
outfile=""
while [ $# -gt 0 ]; do
  case "$1" in
    -d)
      shift
      dir="$1"
      ;;
    -o)
      shift
      outfile="$1"
      ;;
  esac
  shift || true
done

if [ -n "$outfile" ]; then
  printf 'metric,value\nmock,1\n' > "$outfile"
else
  printf 'summary:%s\n' "$dir"
fi
EOF

chmod +x "${FAKE_BIN}/fapp" "${FAKE_BIN}/fapppx"
export PATH="${FAKE_BIN}:${PATH}"

run_and_check_default() {
  local archive="${TMP_DIR}/default.tgz"
  local extract_dir="${TMP_DIR}/default_extract"

  bk_profiler fapp --archive "$archive" --raw-dir "${TMP_DIR}/default_pa" -- true
  mkdir -p "$extract_dir"
  tar -xzf "$archive" -C "$extract_dir"

  test -f "${extract_dir}/bk_profiler_artifact/meta.json"
  test -f "${extract_dir}/bk_profiler_artifact/raw/rep1/event.txt"
  test -f "${extract_dir}/bk_profiler_artifact/reports/fapp_A_rep1.txt"
  ! test -f "${extract_dir}/bk_profiler_artifact/reports/cpu_pa_rep1.csv"
  grep -q '"level": "single"' "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q '"report_format": "text"' "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q '"event": "pa1"' "${extract_dir}/bk_profiler_artifact/meta.json"
}

run_and_check_simple_both() {
  local archive="${TMP_DIR}/simple.tgz"
  local extract_dir="${TMP_DIR}/simple_extract"

  bk_profiler fapp --level simple --report-format both --archive "$archive" --raw-dir "${TMP_DIR}/simple_pa" -- true
  mkdir -p "$extract_dir"
  tar -xzf "$archive" -C "$extract_dir"

  test -f "${extract_dir}/bk_profiler_artifact/meta.json"
  test -f "${extract_dir}/bk_profiler_artifact/raw/rep5/event.txt"
  test -f "${extract_dir}/bk_profiler_artifact/reports/fapp_A_rep5.txt"
  test -f "${extract_dir}/bk_profiler_artifact/reports/cpu_pa_rep5.csv"
  grep -q '"level": "simple"' "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q '"report_format": "both"' "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q '"event": "pa5"' "${extract_dir}/bk_profiler_artifact/meta.json"
}

run_and_check_default
run_and_check_simple_both

echo "bk_profiler tests passed"

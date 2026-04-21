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
  if [ "${FAKE_FAPP_FAIL:-0}" = "1" ]; then
    exit 23
  fi
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

cat > "${FAKE_BIN}/ncu" <<'EOF'
#!/bin/bash
set -euo pipefail
outfile=""
import_file=""
import_mode=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output)
      shift
      outfile="$1"
      ;;
    --import)
      shift
      import_file="$1"
      import_mode=1
      ;;
    --page|--target-processes|--launch-count|--set)
      shift
      ;;
    --nvtx)
      ;;
    --*)
      ;;
    *)
      if [ "$import_mode" -eq 0 ]; then
        break
      fi
      ;;
  esac
  shift || true
done

if [ "$import_mode" -eq 1 ]; then
  printf 'ncu import:%s\n' "$import_file"
  exit 0
fi

if [ -n "$outfile" ]; then
  mkdir -p "$(dirname "$outfile")"
  printf 'ncu report\n' > "${outfile}.ncu-rep"
fi

"$@"
EOF

chmod +x "${FAKE_BIN}/ncu"

run_and_check_level() {
  local level="$1"
  local expected_last_rep="$2"
  local expected_last_event="$3"
  local expected_format="$4"
  local expect_csv="$5"
  local archive="${TMP_DIR}/${level}.tgz"
  local extract_dir="${TMP_DIR}/${level}_extract"
  local raw_dir="${TMP_DIR}/${level}_pa"

  bk_profiler fapp --level "$level" --archive "$archive" --raw-dir "$raw_dir" -- true
  mkdir -p "$extract_dir"
  tar -xzf "$archive" -C "$extract_dir"

  test -f "${extract_dir}/bk_profiler_artifact/meta.json"
  test -f "${extract_dir}/bk_profiler_artifact/raw/rep1/event.txt"
  test -f "${extract_dir}/bk_profiler_artifact/raw/rep${expected_last_rep}/event.txt"
  test -f "${extract_dir}/bk_profiler_artifact/reports/fapp_A_rep${expected_last_rep}.txt"

  if [ "$expect_csv" = "yes" ]; then
    test -f "${extract_dir}/bk_profiler_artifact/reports/cpu_pa_rep${expected_last_rep}.csv"
  else
    ! test -f "${extract_dir}/bk_profiler_artifact/reports/cpu_pa_rep${expected_last_rep}.csv"
  fi

  grep -q "\"level\": \"${level}\"" "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q "\"report_format\": \"${expected_format}\"" "${extract_dir}/bk_profiler_artifact/meta.json"
  grep -q "\"event\": \"${expected_last_event}\"" "${extract_dir}/bk_profiler_artifact/meta.json"
}

run_and_check_level single 1 pa1 text no
run_and_check_level simple 5 pa5 both yes
run_and_check_level standard 11 pa11 both yes
run_and_check_level detailed 17 pa17 both yes

ncu_archive="${TMP_DIR}/ncu.tgz"
ncu_extract="${TMP_DIR}/ncu_extract"
ncu_raw="${TMP_DIR}/ncu_pa"
bk_profiler ncu --level single --archive "$ncu_archive" --raw-dir "$ncu_raw" -- bash -c 'printf "ncu target\n"'
mkdir -p "$ncu_extract"
tar -xzf "$ncu_archive" -C "$ncu_extract"
test -f "${ncu_extract}/bk_profiler_artifact/meta.json"
test -f "${ncu_extract}/bk_profiler_artifact/raw/rep1/profile.ncu-rep"
test -f "${ncu_extract}/bk_profiler_artifact/reports/ncu_import_rep1.txt"
grep -q '"tool": "ncu"' "${ncu_extract}/bk_profiler_artifact/meta.json"
grep -q '"kind": "ncu_report"' "${ncu_extract}/bk_profiler_artifact/meta.json"
grep -q '"ncu_options": \["--target-processes", "all", "--set", "basic", "--launch-count", "1"\]' "${ncu_extract}/bk_profiler_artifact/meta.json"

ncu_detailed_archive="${TMP_DIR}/ncu_detailed.tgz"
ncu_detailed_extract="${TMP_DIR}/ncu_detailed_extract"
ncu_detailed_raw="${TMP_DIR}/ncu_detailed_pa"
bk_profiler ncu --level detailed --archive "$ncu_detailed_archive" --raw-dir "$ncu_detailed_raw" -- bash -c 'printf "ncu detailed target\n"'
mkdir -p "$ncu_detailed_extract"
tar -xzf "$ncu_detailed_archive" -C "$ncu_detailed_extract"
grep -q '"ncu_options": \["--target-processes", "all", "--set", "full", "--nvtx"\]' "${ncu_detailed_extract}/bk_profiler_artifact/meta.json"

fapp_fail_archive="${TMP_DIR}/fapp_fail.tgz"
fapp_fail_extract="${TMP_DIR}/fapp_fail_extract"
fapp_fail_raw="${TMP_DIR}/fapp_fail_pa"
export FAKE_FAPP_FAIL=1
if bk_profiler fapp --level single --archive "$fapp_fail_archive" --raw-dir "$fapp_fail_raw" -- true; then
  echo "expected failing fapp target to propagate non-zero status" >&2
  exit 1
else
  fapp_fail_status=$?
fi
unset FAKE_FAPP_FAIL
test "$fapp_fail_status" -eq 23
mkdir -p "$fapp_fail_extract"
tar -xzf "$fapp_fail_archive" -C "$fapp_fail_extract"
test -f "${fapp_fail_extract}/bk_profiler_artifact/meta.json"
test -f "${fapp_fail_extract}/bk_profiler_artifact/raw/rep1/event.txt"
grep -q '"fapp_events": \["pa1"\]' "${fapp_fail_extract}/bk_profiler_artifact/meta.json"

ncu_fail_archive="${TMP_DIR}/ncu_fail.tgz"
ncu_fail_extract="${TMP_DIR}/ncu_fail_extract"
ncu_fail_raw="${TMP_DIR}/ncu_fail_pa"
if bk_profiler ncu --level single --archive "$ncu_fail_archive" --raw-dir "$ncu_fail_raw" -- bash -c 'exit 42'; then
  echo "expected failing ncu target to propagate non-zero status" >&2
  exit 1
else
  ncu_fail_status=$?
fi
test "$ncu_fail_status" -eq 42
mkdir -p "$ncu_fail_extract"
tar -xzf "$ncu_fail_archive" -C "$ncu_fail_extract"
test -f "${ncu_fail_extract}/bk_profiler_artifact/meta.json"
test -f "${ncu_fail_extract}/bk_profiler_artifact/raw/rep1/profile.ncu-rep"

echo "bk_profiler tests passed"

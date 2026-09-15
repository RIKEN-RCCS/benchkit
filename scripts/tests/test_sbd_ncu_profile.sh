#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping SBD NCU profile test"
  exit 0
fi

source "${REPO_DIR}/scripts/bk_functions.sh"
export SBD_BENCHKIT_ROOT="${REPO_DIR}"
source "${REPO_DIR}/programs/sbd/profile.sh"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

FAKE_BIN="${TMP_DIR}/bin"
RUN_DIR="${TMP_DIR}/run"
RESULTS_DIR="${TMP_DIR}/results"
FAKE_NCU_LOG="${TMP_DIR}/ncu-kernels.log"
export FAKE_NCU_LOG RESULTS_DIR

mkdir -p "${FAKE_BIN}" "${RUN_DIR}" "${RESULTS_DIR}"

cat > "${FAKE_BIN}/mpirun" <<'EOF'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "-np" ]; then
  shift 2
fi

OMPI_COMM_WORLD_RANK=0 OMPI_COMM_WORLD_LOCAL_RANK=0 "$@"
EOF

cat > "${FAKE_BIN}/nsys" <<'EOF'
#!/bin/bash
set -euo pipefail

case "${1:-}" in
  profile)
    shift
    output=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -o)
          shift
          output="$1"
          ;;
        --*)
          ;;
        *)
          break
          ;;
      esac
      shift || true
    done
    test -n "$output"
    "$@" >/dev/null
    mkdir -p "$(dirname "$output")"
    printf 'fake nsys report\n' > "${output}.nsys-rep"
    ;;
  stats)
    shift
    output=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --output)
          shift
          output="$1"
          ;;
      esac
      shift || true
    done
    test -n "$output"
    cat > "${output}_cuda_gpu_kern_sum.csv" <<'CSV'
CUDA Kernel Summary
"Time (%)","Total Time (ns)","Instances","Avg (ns)","Med (ns)","Min (ns)","Max (ns)","StdDev (ns)","Name"
58.5,"5,850,000",50,117000,116000,100000,130000,4000,"void sbd::MultAlphaBeta<double>(double*, double const*)"
19.2,"1,920,000",50,38400,38000,35000,42000,2000,"void sbd::MultUnified<double, (int)0, (int)1>(double*, double const*)"
17.0,"1,700,000",50,34000,33800,30000,39000,1800,"void sbd::MultUnified<double, (int)1, (int)1>(double*, double const*)"
2.7,"270,000",50,5400,5300,5000,6500,400,"void sbd::MultUnified<double, (int)0, (int)0>(double*, double const*)"
2.5,"250,000",50,5000,4900,4500,6000,350,"void sbd::MultUnified<double, (int)1, (int)0>(double*, double const*)"
CSV
    printf 'Name,Time\ncuLaunchKernel,1\n' > "${output}_cuda_api_sum.csv"
    ;;
  *)
    exit 2
    ;;
esac
EOF

cat > "${FAKE_BIN}/ncu" <<'EOF'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "--import" ]; then
  printf 'metric,value\nfake,1\n'
  exit 0
fi

output=""
kernel=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output)
      shift
      output="$1"
      ;;
    --kernel-name)
      shift
      kernel="$1"
      ;;
    --kernel-name-base|--launch-skip|--launch-count|--target-processes|--set)
      shift
      ;;
    --nvtx)
      ;;
    ./*)
      "$@" >/dev/null
      break
      ;;
  esac
  shift || true
done

test -n "$output"
mkdir -p "$(dirname "$output")"
printf '%s\n' "$kernel" >> "$FAKE_NCU_LOG"
printf 'fake ncu report\n' > "${output}.ncu-rep"
EOF

cat > "${RUN_DIR}/diag" <<'EOF'
#!/bin/bash
set -euo pipefail
printf 'fake SBD diag\n'
EOF

chmod +x "${FAKE_BIN}/mpirun" "${FAKE_BIN}/nsys" "${FAKE_BIN}/ncu" "${RUN_DIR}/diag"
export PATH="${FAKE_BIN}:${PATH}"

(
  unset BK_PROFILER BK_PROFILER_LEVEL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL SBD_PROFILER_TOOL
  sbd_configure_ncu_profile_from_run_env RC_FX700
  test -z "${BK_SBD_NCU_PROFILE:-}"
)

(
  unset BK_PROFILER BK_PROFILER_LEVEL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL
  export SBD_PROFILER_TOOL=none
  sbd_configure_ncu_profile_from_run_env RIKYU
  test "${BK_SBD_NCU_PROFILE:-}" = "false"
)

pushd "${RUN_DIR}" >/dev/null
unset BK_PROFILER SBD_PROFILER_TOOL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL
export BK_SBD_NCU_PROFILE_MODE=discovery
export BK_SBD_NCU_PLAN_TOP_K=5
export BK_PROFILER_LEVEL=single
sbd_configure_ncu_profile_from_run_env RIKYU
test "${BK_SBD_NCU_PROFILE}" = "true"
test "${BK_SBD_NCU_PROFILER_LEVEL}" = "single"
sbd_run_configured_ncu_profiles RIKYU 4 \
  --fcidump fcidump.txt \
  --adetfile h2o-1em7-alpha.txt
popd >/dev/null

test -f "${RESULTS_DIR}/sbd_nsys_kernel_discovery.nsys-rep"
test -f "${RESULTS_DIR}/sbd_nsys_stats_cuda_gpu_kern_sum.csv"
test -f "${RESULTS_DIR}/sbd_kernel_discovery.json"
test -f "${RESULTS_DIR}/sbd_ncu_plan.json"

jq -e '
  (.profiles | length) == 5 and
  ([.profiles[].kernel_match.pattern] | unique | length) == 5 and
  .profiles[1].kernel_match.pattern == "regex:.*sbd::MultUnified<double,[[:space:]]*\\(int\\)0,[[:space:]]*\\(int\\)1>.*" and
  .profiles[4].kernel_match.pattern == "regex:.*sbd::MultUnified<double,[[:space:]]*\\(int\\)1,[[:space:]]*\\(int\\)0>.*"
' "${RESULTS_DIR}/sbd_ncu_plan.json" >/dev/null

mapfile -t profile_archives < <(find "${RESULTS_DIR}" -maxdepth 1 -type f -name 'padata_*.tgz' | sort)
mapfile -t profile_metadata < <(find "${RESULTS_DIR}" -maxdepth 1 -type f -name 'padata_*.metadata.json' | sort)
test "${#profile_archives[@]}" -eq 5
test "${#profile_metadata[@]}" -eq 5

artifact_count=$(printf '%s\n' "${SBD_MULT_SECTION_ARTIFACTS}" | tr ',' '\n' | awk 'NF { count += 1 } END { print count + 0 }')
test "$artifact_count" -eq 5

jq -e '
  .kind == "gpu_kernel_profile_metadata" and
  .profiler == "ncu" and
  .section == "mult" and
  .nsys_discovery.section == "mult" and
  (.nsys_discovery.kernel_match.pattern | contains("MultUnified"))
' "${profile_metadata[1]}" >/dev/null

for archive in "${profile_archives[@]}"; do
  tar -tzf "$archive" | grep -q 'bk_profiler_artifact/meta.json'
  tar -tzf "$archive" | grep -q 'bk_profiler_artifact/raw/rep1/profile_raw.csv'
  if tar -tzf "$archive" | grep -q '.ncu-rep$'; then
    echo "SBD profile archive should omit .ncu-rep by default" >&2
    exit 1
  fi
done

grep -Fq 'regex:.*sbd::MultUnified<double,[[:space:]]*\(int\)0,[[:space:]]*\(int\)1>.*' "$FAKE_NCU_LOG"

echo "SBD NCU profile test passed"

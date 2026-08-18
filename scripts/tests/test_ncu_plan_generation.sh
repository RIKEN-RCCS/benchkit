#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

PYTHON_BIN="${PYTHON_BIN:-python3}"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

"${PYTHON_BIN}" "${REPO_DIR}/scripts/profiling/generate_ncu_plan.py" \
  --nsys-csv "${REPO_DIR}/scripts/tests/fixtures/nsys_cuda_gpu_kern_sum.csv" \
  --out-discovery "${TMP_DIR}/kernel_discovery.json" \
  --out-plan "${TMP_DIR}/ncu_plan.json" \
  --top-k 3 \
  --min-total-time-pct 3 \
  --launch-count 10 \
  --warmup-fraction 0.10 \
  --max-launch-skip 20

"${PYTHON_BIN}" "${REPO_DIR}/scripts/profiling/render_ncu_plan_commands.py" \
  --plan "${TMP_DIR}/ncu_plan.json" \
  --out "${TMP_DIR}/ncu_commands.json" \
  --format json \
  --level detailed \
  --archive-dir results \
  --raw-dir-prefix ncu_auto \
  -- ./app --input case.inp >/dev/null

"${PYTHON_BIN}" "${REPO_DIR}/scripts/profiling/iter_ncu_plan_profiles.py" \
  --plan "${TMP_DIR}/ncu_plan.json" > "${TMP_DIR}/ncu_plan_profiles.tsv"

test -f "${TMP_DIR}/kernel_discovery.json"
test -f "${TMP_DIR}/ncu_plan.json"
test -f "${TMP_DIR}/ncu_commands.json"
test -f "${TMP_DIR}/ncu_plan_profiles.tsv"

jq -e '
  .schema_version == 1 and
  .summary.kernel_count == 5 and
  .kernels[0].instances == 120 and
  .kernels[0].source_launches == 120 and
  .kernels[0].source_gpu_duration_ns == 6350000 and
  .kernels[0].discovery_gpu_time_pct == 63.5 and
  (.kernels[0].name | contains("inter_cell"))
' "${TMP_DIR}/kernel_discovery.json" >/dev/null

jq -e '
  .schema_version == 1 and
  .policy.metric_set == "gpu_kernel_estimation" and
  (.profiles | length) == 3 and
  .profiles[0].launch_skip == 12 and
  .profiles[0].launch_count == 10 and
  .profiles[0].kernel_match.name_base == "demangled" and
  .profiles[0].section == null and
  .profiles[0].kernel_match.pattern == "regex:.*kern_compute_force_nonbond_table_linear_univ__inter_cell.*" and
  .profiles[1].kernel_match.pattern == "regex:.*kern_compute_force_nonbond_table_linear_univ__intra_cell.*" and
  .profiles[2].kernel_match.pattern == "regex:.*kern_build_pairlist.*" and
  (.profiles[2].kernel_name | contains("build_pairlist"))
' "${TMP_DIR}/ncu_plan.json" >/dev/null

if jq -r '.profiles[].kernel_match.pattern' "${TMP_DIR}/ncu_plan.json" | grep -q '[[:space:]]'; then
  echo "generated NCU regex patterns must not contain whitespace" >&2
  exit 1
fi

if jq -e '.profiles[].kernel_name | contains("tiny_kernel")' "${TMP_DIR}/ncu_plan.json" >/dev/null; then
  echo "tiny low-impact kernel should not be selected" >&2
  exit 1
fi

cat > "${TMP_DIR}/dominant_nsys.csv" <<'CSV'
CUDA Kernel Summary
"Time (%)","Total Time (ns)","Instances","Avg (ns)","Med (ns)","Min (ns)","Max (ns)","StdDev (ns)","Name"
97.5,"9,750,000",120,81250,81000,79000,90000,1200,"void kern_compute_force_nonbond_table_linear_univ__force_inter_cell(float*)"
1.5,"150,000",120,1250,1200,1000,2000,200,"void kern_compute_force_nonbond_table_linear_univ__force_intra_cell(float*)"
0.8,"80,000",12,6666,6500,6000,9000,600,"void kern_build_pairlist<4, 256>(float*)"
0.4,"40,000",6,6666,6500,6000,9000,600,"void kern_compute_energy_nonbond_table_linear_univ__energyforce_inter_cell(float*)"
0.2,"20,000",10,2000,1900,1800,2500,100,"void tiny_kernel()"
CSV

"${PYTHON_BIN}" "${REPO_DIR}/scripts/profiling/generate_ncu_plan.py" \
  --nsys-csv "${TMP_DIR}/dominant_nsys.csv" \
  --out-plan "${TMP_DIR}/dominant_ncu_plan.json" \
  --top-k 3 \
  --launch-count 10 >/dev/null

jq -e '
  (.profiles | length) == 3 and
  .profiles[0].section == null and
  .profiles[0].kernel_match.pattern == "regex:.*kern_compute_force_nonbond_table_linear_univ__force_inter_cell.*" and
  .profiles[0].launch_skip == 1 and
  .profiles[0].selection.source_gpu_duration_ns == 9750000 and
  .profiles[0].selection.discovery_gpu_time_pct == 97.5 and
  .profiles[1].kernel_match.pattern == "regex:.*kern_compute_force_nonbond_table_linear_univ__force_intra_cell.*" and
  .profiles[2].kernel_match.pattern == "regex:.*kern_build_pairlist.*"
' "${TMP_DIR}/dominant_ncu_plan.json" >/dev/null

"${PYTHON_BIN}" "${REPO_DIR}/scripts/profiling/generate_ncu_plan.py" \
  --nsys-csv "${TMP_DIR}/dominant_nsys.csv" \
  --out-plan "${TMP_DIR}/all_ncu_plan.json" \
  --top-k 0 \
  --launch-count 10 >/dev/null

jq -e '
  (.profiles | length) == 5 and
  .profiles[3].kernel_match.pattern == "regex:.*kern_compute_energy_nonbond_table_linear_univ__energyforce_inter_cell.*"
' "${TMP_DIR}/all_ncu_plan.json" >/dev/null

jq -e '
  .schema_version == 1 and
  .execution.profiler == "ncu" and
  .execution.level == "detailed" and
  (.commands | length) == 3 and
  .commands[0].env.BK_PROFILER_NCU_RAW_CSV == "true" and
  (.commands[0].env.BK_PROFILER_ARGS | contains("--kernel-name-base")) and
  (.commands[0].env.BK_PROFILER_ARGS | contains("\u0027") | not) and
  (.commands[0].env.BK_PROFILER_ARGS | contains("\"") | not) and
  (.commands[0].env.BK_PROFILER_ARGS | contains("regex:.*kern_compute_force_nonbond_table_linear_univ__inter_cell.*")) and
  (.commands[0].argv | index("bk_profiler") == 0) and
  (.commands[0].argv | index("--archive") != null) and
  (.commands[0].argv | index("./app") != null)
' "${TMP_DIR}/ncu_commands.json" >/dev/null

awk -F '\t' 'NF != 6 { exit 1 } $2 != "-" { exit 1 } $6 == "" { exit 1 }' "${TMP_DIR}/ncu_plan_profiles.tsv"

echo "ncu plan generation tests passed"

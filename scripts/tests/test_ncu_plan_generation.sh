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

test -f "${TMP_DIR}/kernel_discovery.json"
test -f "${TMP_DIR}/ncu_plan.json"
test -f "${TMP_DIR}/ncu_commands.json"

jq -e '
  .schema_version == 1 and
  .summary.kernel_count == 5 and
  .kernels[0].instances == 120 and
  (.kernels[0].name | contains("inter_cell"))
' "${TMP_DIR}/kernel_discovery.json" >/dev/null

jq -e '
  .schema_version == 1 and
  .policy.metric_set == "gpu_kernel_estimation" and
  (.profiles | length) == 3 and
  .profiles[0].launch_skip == 12 and
  .profiles[0].launch_count == 10 and
  .profiles[0].kernel_match.name_base == "demangled" and
  (.profiles[0].kernel_match.pattern | startswith("regex:^")) and
  (.profiles[2].kernel_name | contains("build_pairlist"))
' "${TMP_DIR}/ncu_plan.json" >/dev/null

if jq -e '.profiles[].kernel_name | contains("tiny_kernel")' "${TMP_DIR}/ncu_plan.json" >/dev/null; then
  echo "tiny low-impact kernel should not be selected" >&2
  exit 1
fi

jq -e '
  .schema_version == 1 and
  .execution.profiler == "ncu" and
  .execution.level == "detailed" and
  (.commands | length) == 3 and
  .commands[0].env.BK_PROFILER_NCU_RAW_CSV == "true" and
  (.commands[0].env.BK_PROFILER_ARGS | contains("--kernel-name-base")) and
  (.commands[0].argv | index("bk_profiler") == 0) and
  (.commands[0].argv | index("--archive") != null) and
  (.commands[0].argv | index("./app") != null)
' "${TMP_DIR}/ncu_commands.json" >/dev/null

echo "ncu plan generation tests passed"

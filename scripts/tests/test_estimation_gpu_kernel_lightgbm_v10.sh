#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping gpu_kernel_lightgbm_v10 estimation test"
  exit 0
fi

PYTHON_BIN="${BK_TEST_ESTIMATION_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$candidate")
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11+ not found; skipping gpu_kernel_lightgbm_v10 estimation test"
  exit 0
fi
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Python 3.11+ not found; skipping gpu_kernel_lightgbm_v10 estimation test"
  exit 0
fi

cat > "${TMP_DIR}/lightgbm_pred.csv" <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,O-Memory Throughput [%],O-Achieved Occupancy,O-breakdown_memory,O-breakdown_pipeline_contention,O-breakdown_sync,O-breakdown_scheduling_overhead
kern_inter,H100,A100,1000,51.5,70.1,0.5,0.2,0.1,0.2
kern_intra,H100,A100,2000,48.0,69.0,0.4,0.3,0.1,0.2
EOF

cat > "${TMP_DIR}/lightgbm_input.csv" <<'EOF'
Kernel Name,Duration [ns]
kern_inter,1000
kern_intra,2000
EOF

cat > "${TMP_DIR}/breakdown.json" <<EOF
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 0.009,
      "estimation_package": "gpu_kernel_lightgbm_v10",
      "artifacts": [
        {"path": "${TMP_DIR}/lightgbm_pred.csv"}
      ]
    },
    {
      "name": "cpu_tail",
      "bench_time": 0.001,
      "estimation_package": "identity"
    }
  ],
  "overlaps": []
}
EOF

pushd "${REPO_DIR}" >/dev/null
source scripts/estimation/common.sh
source scripts/estimation/packages/instrumented_app_sections_dummy.sh

export BK_GPU_LIGHTGBM_ARTIFACT_MODE="prediction"
export BK_GPU_LIGHTGBM_FETCH_PERFTOOLS=false
export BK_GPU_LIGHTGBM_INPUT_CSV="${TMP_DIR}/lightgbm_input.csv"
export BK_GPU_LIGHTGBM_PYTHON="$PYTHON_BIN"

transformed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null
unset BK_GPU_LIGHTGBM_INPUT_CSV

echo "$transformed" | jq -e '
  (.sections | length == 2) and
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].time == 0.009 and
  .sections[0].bench_time == 0.009 and
  .sections[0].scaling_method == "identity" and
  .sections[0].estimation_package == "identity" and
  .sections[0].requested_estimation_package == "gpu_kernel_lightgbm_v10" and
  .sections[0].fallback_used == "identity" and
  .sections[0].package_applicability.status == "fallback" and
  (.sections[0].package_applicability.missing_inputs | index("gpu_kernel_section_kernel_selector_required")) and
  .sections[0].metrics.kernel_count == 2 and
  .sections[0].metrics.unique_kernel_count == 2 and
  .sections[0].metrics.time_column == "O-Execution Time" and
  .sections[0].metrics.source_time_column == "Duration [ns]" and
  .sections[0].metrics.total_source_time_ns == 3000 and
  .sections[0].metrics.total_predicted_time_ns == 3000 and
  .sections[0].metrics.sample_predicted_time == 0.000003 and
  .sections[0].metrics.app_gpu_section_time == 0.009 and
  .sections[0].metrics.section_time_ratio_predicted_over_source == 1 and
  .sections[0].metrics.time_ratio_predicted_over_source == 1 and
  .sections[0].metrics.speedup_factor_source_over_predicted == 1 and
  .sections[0].metrics.source_gpus == ["H100"] and
  .sections[0].metrics.target_gpus == ["A100"] and
  .sections[0].metrics.kernels[0].name == "kern_inter" and
  .sections[0].metrics.kernels[0].source_time_ns == 1000 and
  .sections[0].metrics.kernels[0].time_ratio_predicted_over_source == 1 and
  .sections[0].metrics.kernels[0].metrics."O-Memory Throughput [%]" == 51.5 and
  (.sections[0].artifacts | map(.kind) | index("gpu_lightgbm_prediction_csv") != null) and
  (.sections[0].artifacts | map(.kind) | index("gpu_lightgbm_input_csv") != null) and
  .sections[1].time == 0.001
' >/dev/null

FAKE_PERFTOOLS="${TMP_DIR}/PerfTools"
mkdir -p "${FAKE_PERFTOOLS}/LightGBM_model/1.0/AI_model"
cat > "${FAKE_PERFTOOLS}/LightGBM_model/1.0/AI_model/run_inference.py" <<'PY'
raise SystemExit(7)
PY

cat > "${TMP_DIR}/input.csv" <<'EOF'
Kernel Name,Duration [ns]
probe_kernel,1000
EOF

cat > "${TMP_DIR}/breakdown_input.json" <<EOF
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 0.011,
      "estimation_package": "gpu_kernel_lightgbm_v10",
      "artifacts": [
        {"path": "${TMP_DIR}/input.csv"}
      ]
    }
  ],
  "overlaps": []
}
EOF

pushd "${REPO_DIR}" >/dev/null
export BK_GPU_LIGHTGBM_ARTIFACT_MODE="input"
export BK_GPU_LIGHTGBM_PERFTOOLS_ROOT="${FAKE_PERFTOOLS}"
export BK_GPU_LIGHTGBM_OUTPUT_DIR="${TMP_DIR}/lightgbm_outputs"
if bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown_input.json")" "1" "1" "1" "identity" "identity" >/tmp/benchkit-lightgbm-unexpected.out 2>"${TMP_DIR}/lightgbm_failure.err"; then
  echo "expected failing LightGBM predictor to fail the transform" >&2
  cat /tmp/benchkit-lightgbm-unexpected.out >&2
  exit 1
fi
popd >/dev/null
grep -q "PerfTools LightGBM_model/1.0 inference failed" "${TMP_DIR}/lightgbm_failure.err"
grep -q "section package gpu_kernel_lightgbm_v10 failed" "${TMP_DIR}/lightgbm_failure.err"

cat > "${TMP_DIR}/weak_breakdown.json" <<'EOF'
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 10,
      "estimation_package": "gpu_kernel_lightgbm_v10"
    },
    {
      "name": "comm",
      "bench_time": 2,
      "estimation_package": "logp"
    }
  ],
  "overlaps": []
}
EOF

pushd "${REPO_DIR}" >/dev/null
source scripts/estimation/packages/weakscaling.sh
normalized=$(bk_estimation_package_normalize_recorded_current_breakdown "$(cat "${TMP_DIR}/weak_breakdown.json")")
current_breakdown=$(bk_top_level_transform_breakdown "$normalized" "1" "1" "1" "identity" "identity")
popd >/dev/null

echo "$current_breakdown" | jq -e '
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].estimation_package == "identity" and
  .sections[0].time == 10 and
  (.sections[0].requested_estimation_package // "") == "" and
  (.sections[0].fallback_used // "") == "" and
  .sections[1].name == "comm" and
  .sections[1].estimation_package == "logp"
' >/dev/null

echo "gpu_kernel_lightgbm_v10 section estimation test passed"

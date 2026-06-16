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
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; skipping gpu_kernel_lightgbm_v10 estimation test"
  exit 0
fi

cat > "${TMP_DIR}/lightgbm_pred.csv" <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,O-Memory Throughput [%],O-Achieved Occupancy,O-breakdown_memory,O-breakdown_pipeline_contention,O-breakdown_sync,O-breakdown_scheduling_overhead
kern_inter,H100,A100,1000,51.5,70.1,0.5,0.2,0.1,0.2
kern_intra,H100,A100,2000,48.0,69.0,0.4,0.3,0.1,0.2
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
export BK_GPU_LIGHTGBM_PYTHON="python3"

transformed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null

echo "$transformed" | jq -e '
  (.sections | length == 2) and
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].time == 0.000003 and
  .sections[0].bench_time == 0.009 and
  .sections[0].scaling_method == "gpu-kernel-lightgbm-v1.0" and
  .sections[0].estimation_package == "gpu_kernel_lightgbm_v10" and
  .sections[0].package_applicability.status == "applicable" and
  .sections[0].metrics.kernel_count == 2 and
  .sections[0].metrics.time_column == "O-Execution Time" and
  .sections[0].metrics.source_gpus == ["H100"] and
  .sections[0].metrics.target_gpus == ["A100"] and
  .sections[0].metrics.kernels[0].name == "kern_inter" and
  .sections[0].metrics.kernels[0].metrics."O-Memory Throughput [%]" == 51.5 and
  .sections[0].artifacts[-1].kind == "gpu_lightgbm_prediction_csv" and
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

echo "gpu_kernel_lightgbm_v10 section estimation test passed"

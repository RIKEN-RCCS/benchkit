#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

command -v jq >/dev/null || {
  echo "SKIP: jq is required"
  exit 0
}

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "SKIP: python3.11+ is required"
  exit 0
fi
if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "SKIP: python3.11+ is required"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/scripts/estimation" "${TMP_DIR}/scripts/result_server"
cp "${REPO_DIR}/scripts/estimation/common.sh" "${TMP_DIR}/scripts/estimation/common.sh"
cp "${REPO_DIR}/scripts/result_server/api.sh" "${TMP_DIR}/scripts/result_server/api.sh"
cp -R "${REPO_DIR}/scripts/estimation/packages" "${TMP_DIR}/scripts/estimation/packages"
cp -R "${REPO_DIR}/scripts/estimation/section_packages" "${TMP_DIR}/scripts/estimation/section_packages"

cat > "${TMP_DIR}/lightgbm_pred.csv" <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,O-Memory Throughput [%]
kern_a,H100,A100,1000,50
kern_b,H100,A100,2000,40
EOF

cat > "${TMP_DIR}/mlp_pred.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu,Execution Time [ns],Memory Throughput [%]
kern_a,H100,A100,3000,30
kern_b,H100,A100,5000,20
EOF

cat > "${TMP_DIR}/source_input.csv" <<'EOF'
Kernel Name,Duration [ns]
kern_a,1000
kern_b,2000
EOF

cat > "${TMP_DIR}/breakdown.json" <<'EOF'
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "time": 10,
      "estimation_package": "gpu_kernel_ensemble_average",
      "artifacts": [{"path": "results/padata0.tgz", "type": "file_reference"}]
    }
  ],
  "overlaps": []
}
EOF

pushd "${TMP_DIR}" >/dev/null
source scripts/estimation/common.sh
source scripts/estimation/packages/instrumented_app_sections_dummy.sh

export BK_GPU_KERNEL_ENSEMBLE_PACKAGES="gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15"
export BK_GPU_LIGHTGBM_ARTIFACT_MODE="prediction"
export BK_GPU_LIGHTGBM_PREDICTION_CSV="${TMP_DIR}/lightgbm_pred.csv"
export BK_GPU_LIGHTGBM_INPUT_CSV="${TMP_DIR}/source_input.csv"
export BK_GPU_LIGHTGBM_PYTHON="$PYTHON_BIN"
export BK_GPU_MLP_ARTIFACT_MODE="prediction"
export BK_GPU_MLP_PREDICTION_CSV="${TMP_DIR}/mlp_pred.csv"
export BK_GPU_MLP_INPUT_CSV="${TMP_DIR}/source_input.csv"
export BK_GPU_MLP_PYTHON="$PYTHON_BIN"

transformed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null

if ! echo "$transformed" | jq -e '
  def near($a; $b):
    (($a - $b) | if . < 0 then -. else . end) < 0.000000000001;

  (.sections | length == 1) and
  .sections[0].estimation_package == "gpu_kernel_ensemble_average" and
  near(.sections[0].time; 18.333333333333336) and
  .sections[0].scaling_method == "gpu-kernel-ensemble-average" and
  .sections[0].metrics.aggregation == "mean" and
  .sections[0].metrics.candidate_count == 2 and
  .sections[0].metrics.applicable_candidate_count == 2 and
  .sections[0].metrics.candidate_packages == ["gpu_kernel_lightgbm_v10", "gpu_kernel_mlp_v15"] and
  near(.sections[0].metrics.mean_time_ratio_predicted_over_source; 1.8333333333333333) and
  (.sections[0].candidate_estimates | length == 2) and
  near(.sections[0].candidate_estimates[0].time; 10) and
  near(.sections[0].candidate_estimates[1].time; 26.666666666666668) and
  near(.sections[0].candidate_estimates[0].metrics.time_ratio_predicted_over_source; 1) and
  near(.sections[0].candidate_estimates[1].metrics.time_ratio_predicted_over_source; 2.6666666666666665)
' >/dev/null; then
  echo "Unexpected ensemble transform output:" >&2
  echo "$transformed" | jq . >&2
  exit 1
fi

echo "gpu_kernel_ensemble_average section estimation test passed"

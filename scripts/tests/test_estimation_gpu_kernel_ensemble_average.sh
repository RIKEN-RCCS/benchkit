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
cp "${REPO_DIR}/scripts/estimation/declarations.sh" "${TMP_DIR}/scripts/estimation/declarations.sh"
cp "${REPO_DIR}/scripts/result_server/api.sh" "${TMP_DIR}/scripts/result_server/api.sh"
cp -R "${REPO_DIR}/scripts/estimation/packages" "${TMP_DIR}/scripts/estimation/packages"
cp -R "${REPO_DIR}/scripts/estimation/section_packages" "${TMP_DIR}/scripts/estimation/section_packages"

cat > "${TMP_DIR}/lightgbm_pred_single.csv" <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,O-Memory Throughput [%]
kern_a,H100,A100,1000,50
EOF

cat > "${TMP_DIR}/mlp_pred_single.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu,Execution Time [ns],Memory Throughput [%]
kern_a,H100,A100,3000,30
EOF

cat > "${TMP_DIR}/mlp_pred_zero.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu,Execution Time [ns],Memory Throughput [%]
kern_a,H100,A100,0,30
EOF

cat > "${TMP_DIR}/source_input_single.csv" <<'EOF'
Kernel Name,Duration [ns],Memory Throughput [%],Achieved Occupancy
kern_a,1000,25,10
EOF

cat > "${TMP_DIR}/lightgbm_pred_mixed.csv" <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,O-Memory Throughput [%]
kern_a,H100,A100,1000,50
EOF

cat > "${TMP_DIR}/mlp_pred_mixed.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu,Execution Time [ns],Memory Throughput [%]
kern_a,H100,A100,3000,30
kern_b,H100,A100,5000,20
EOF

cat > "${TMP_DIR}/source_input_mixed.csv" <<'EOF'
Kernel Name,Duration [ns],Memory Throughput [%],Achieved Occupancy
kern_a,1000,25,10
kern_b,2000,40,20
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
source scripts/estimation/section_packages/gpu_kernel_ensemble_average.sh

export BK_GPU_KERNEL_ENSEMBLE_PACKAGES="gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15"
export BK_GPU_LIGHTGBM_ARTIFACT_MODE="prediction"
export BK_GPU_LIGHTGBM_PREDICTION_CSV="${TMP_DIR}/lightgbm_pred_single.csv"
export BK_GPU_LIGHTGBM_INPUT_CSV="${TMP_DIR}/source_input_single.csv"
export BK_GPU_LIGHTGBM_PYTHON="$PYTHON_BIN"
export BK_GPU_MLP_ARTIFACT_MODE="prediction"
export BK_GPU_MLP_PREDICTION_CSV="${TMP_DIR}/mlp_pred_single.csv"
export BK_GPU_MLP_INPUT_CSV="${TMP_DIR}/source_input_single.csv"
export BK_GPU_MLP_PYTHON="$PYTHON_BIN"

transformed_single=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")

unset BK_GPU_KERNEL_ENSEMBLE_PACKAGES
default_packages=$(_bk_gpu_kernel_ensemble_packages "$(cat "${TMP_DIR}/breakdown.json")" | paste -sd, -)
test "$default_packages" = "gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15,gpu_kernel_mlp_v21,gpu_kernel_mlp_v40,gpu_kernel_mlp_v41"
export BK_GPU_KERNEL_ENSEMBLE_PACKAGES="gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15"

export BK_GPU_MLP_PREDICTION_CSV="${TMP_DIR}/mlp_pred_zero.csv"
transformed_zero_candidate=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")

export BK_GPU_LIGHTGBM_PREDICTION_CSV="${TMP_DIR}/lightgbm_pred_mixed.csv"
export BK_GPU_LIGHTGBM_INPUT_CSV="${TMP_DIR}/source_input_mixed.csv"
export BK_GPU_MLP_PREDICTION_CSV="${TMP_DIR}/mlp_pred_mixed.csv"
export BK_GPU_MLP_INPUT_CSV="${TMP_DIR}/source_input_mixed.csv"

transformed_mixed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")

export BK_GPU_KERNEL_SECTION_GPU_KERNEL_REGION_REGEX="kern_a"
transformed_selected=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null

if ! echo "$transformed_single" | jq -e '
  def near($a; $b):
    (($a - $b) | if . < 0 then -. else . end) < 0.000000000001;

  (.sections | length == 1) and
  .sections[0].estimation_package == "gpu_kernel_ensemble_average" and
  near(.sections[0].time; 20) and
  .sections[0].scaling_method == "gpu-kernel-ensemble-average" and
  .sections[0].bench_time == 10 and
  .sections[0].metrics.aggregation == "single-kernel-package-ratio-mean" and
  .sections[0].metrics.candidate_count == 2 and
  .sections[0].metrics.applicable_candidate_count == 2 and
  .sections[0].metrics.candidate_packages == ["gpu_kernel_lightgbm_v10", "gpu_kernel_mlp_v15"] and
  (.sections[0].metrics.package_summaries | length == 2) and
  .sections[0].metrics.package_summaries[0].estimation_package == "gpu_kernel_lightgbm_v10" and
  .sections[0].metrics.package_summaries[0].source_section_time == 10 and
  near(.sections[0].metrics.package_summaries[0].projected_section_time; 10) and
  near(.sections[0].metrics.package_summaries[0].time_ratio_predicted_over_source; 1) and
  .sections[0].metrics.package_summaries[0].source_gpus == ["H100"] and
  .sections[0].metrics.package_summaries[0].target_gpus == ["A100"] and
  .sections[0].metrics.package_summaries[0].ncu_sample.kernel_count == 1 and
  .sections[0].metrics.package_summaries[0].ncu_sample.source_time_ns == 1000 and
  .sections[0].metrics.package_summaries[0].ncu_sample.predicted_time_ns == 1000 and
  .sections[0].metrics.package_summaries[1].estimation_package == "gpu_kernel_mlp_v15" and
  near(.sections[0].metrics.package_summaries[1].projected_section_time; 30) and
  near(.sections[0].metrics.package_summaries[1].time_ratio_predicted_over_source; 3) and
  (.sections[0].metrics.kernel_summaries | length == 1) and
  .sections[0].metrics.kernel_summaries[0].name == "kern_a" and
  (.sections[0].metrics.kernel_summaries[0].package_summaries | length == 2) and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].estimation_package == "gpu_kernel_lightgbm_v10" and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].sample_count == 1 and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].source_gpus == ["H100"] and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].target_gpus == ["A100"] and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].source_time_ns_total == 1000 and
  .sections[0].metrics.kernel_summaries[0].package_summaries[0].predicted_time_ns_total == 1000 and
  near(.sections[0].metrics.kernel_summaries[0].package_summaries[0].mean_time_ratio_predicted_over_source; 1) and
  (.sections[0].metrics.kernel_summaries[0].package_summaries[0].metric_comparisons | length >= 2) and
  (.sections[0].metrics.kernel_summaries[0].package_summaries[0].metric_comparisons | map(select(.name == "O-Memory Throughput [%]" and .source_value_mean == 25 and .predicted_value_mean == 50 and .ratio_predicted_over_source_mean == 2)) | length == 1) and
  .sections[0].metrics.kernel_summaries[0].package_summaries[1].estimation_package == "gpu_kernel_mlp_v15" and
  near(.sections[0].metrics.kernel_summaries[0].package_summaries[1].mean_time_ratio_predicted_over_source; 3) and
  (.sections[0].metrics.kernel_summaries[0].package_summaries[1].metric_comparisons | map(select(.name == "Memory Throughput [%]" and .source_value_mean == 25 and .predicted_value_mean == 30 and .ratio_predicted_over_source_mean == 1.2)) | length == 1) and
  near(.sections[0].metrics.mean_time_ratio_predicted_over_source; 2) and
  .sections[0].metrics.unique_kernel_count == 1 and
  .sections[0].metrics.kernel_names == ["kern_a"] and
  (.sections[0].candidate_estimates | length == 2) and
  near(.sections[0].candidate_estimates[0].time; 10) and
  near(.sections[0].candidate_estimates[1].time; 30) and
  near(.sections[0].candidate_estimates[0].metrics.time_ratio_predicted_over_source; 1) and
  near(.sections[0].candidate_estimates[1].metrics.time_ratio_predicted_over_source; 3)
' >/dev/null; then
  echo "Unexpected single-kernel ensemble transform output:" >&2
  echo "$transformed_single" | jq . >&2
  exit 1
fi

if ! echo "$transformed_zero_candidate" | jq -e '
  def near($a; $b):
    (($a - $b) | if . < 0 then -. else . end) < 0.000000000001;

  (.sections | length == 1) and
  .sections[0].estimation_package == "gpu_kernel_ensemble_average" and
  near(.sections[0].time; 10) and
  .sections[0].scaling_method == "gpu-kernel-ensemble-average" and
  .sections[0].package_applicability.status == "partially_applicable" and
  (.sections[0].package_applicability.missing_inputs | index("gpu_kernel_ensemble_positive_candidate_ratio_required")) and
  .sections[0].metrics.candidate_count == 2 and
  .sections[0].metrics.applicable_candidate_count == 1 and
  near(.sections[0].metrics.mean_time_ratio_predicted_over_source; 1) and
  (.sections[0].metrics.kernel_candidate_ratios[0].candidate_ratios | length == 1) and
  .sections[0].metrics.kernel_candidate_ratios[0].candidate_ratios[0].estimation_package == "gpu_kernel_lightgbm_v10" and
  (.sections[0].candidate_estimates | length == 2)
' >/dev/null; then
  echo "Unexpected zero-ratio candidate ensemble transform output:" >&2
  echo "$transformed_zero_candidate" | jq . >&2
  exit 1
fi

if ! echo "$transformed_mixed" | jq -e '
  (.sections | length == 1) and
  .sections[0].estimation_package == "identity" and
  .sections[0].requested_estimation_package == "gpu_kernel_ensemble_average" and
  .sections[0].fallback_used == "identity" and
  .sections[0].time == 10 and
  .sections[0].scaling_method == "identity" and
  .sections[0].package_applicability.status == "fallback" and
  (.sections[0].package_applicability.missing_inputs | index("gpu_kernel_section_kernel_selector_required")) and
  (.sections[0].package_applicability.missing_inputs | index("gpu_kernel_ensemble_all_candidate_packages_required")) and
  .sections[0].metrics.unique_kernel_count == 1 and
  .sections[0].metrics.kernel_names == ["kern_a"] and
  (.sections[0].candidate_estimates | length == 2) and
  .sections[0].candidate_estimates[1].metrics.unique_kernel_count == 2 and
  .sections[0].candidate_estimates[1].metrics.kernel_names == ["kern_a", "kern_b"]
' >/dev/null; then
  echo "Unexpected mixed-kernel ensemble transform output:" >&2
  echo "$transformed_mixed" | jq . >&2
  exit 1
fi

if ! echo "$transformed_selected" | jq -e '
  def near($a; $b):
    (($a - $b) | if . < 0 then -. else . end) < 0.000000000001;

  (.sections | length == 1) and
  .sections[0].estimation_package == "gpu_kernel_ensemble_average" and
  near(.sections[0].time; 20) and
  .sections[0].scaling_method == "gpu-kernel-ensemble-average" and
  .sections[0].package_applicability.status == "applicable" and
  .sections[0].metrics.unique_kernel_count == 1 and
  .sections[0].metrics.kernel_names == ["kern_a"] and
  near(.sections[0].metrics.mean_time_ratio_predicted_over_source; 2) and
  (.sections[0].metrics.kernel_candidate_ratios[0].candidate_ratios | length == 2) and
  (.sections[0].candidate_estimates | length == 2) and
  .sections[0].candidate_estimates[0].metrics.kernel_selector.kind == "regex" and
  .sections[0].candidate_estimates[0].metrics.kernel_selector.value == "kern_a" and
  .sections[0].candidate_estimates[1].metrics.kernel_selector.kind == "regex" and
  .sections[0].candidate_estimates[1].metrics.kernel_selector.value == "kern_a"
' >/dev/null; then
  echo "Unexpected selected-kernel ensemble transform output:" >&2
  echo "$transformed_selected" | jq . >&2
  exit 1
fi

echo "gpu_kernel_ensemble_average section estimation test passed"

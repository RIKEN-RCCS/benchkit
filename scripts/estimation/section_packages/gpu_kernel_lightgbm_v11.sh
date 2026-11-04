#!/bin/bash
# PerfTools LightGBM 1.1 adapter, used by the default GPU ensemble.
# shellcheck source=scripts/estimation/section_packages/gpu_kernel_lightgbm_v10.sh
source "${BASH_SOURCE[0]%/*}/gpu_kernel_lightgbm_v10.sh"

bk_section_package_metadata_gpu_kernel_lightgbm_v11() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_lightgbm_v11.metadata.json"
}

bk_section_package_check_applicability_gpu_kernel_lightgbm_v11() {
  local _BK_GPU_LIGHTGBM_VERSION=1.1
  bk_section_package_check_applicability_gpu_kernel_lightgbm_v10 "$@"
}

bk_section_package_transform_gpu_kernel_lightgbm_v11() {
  local _BK_GPU_LIGHTGBM_VERSION=1.1
  local _BK_GPU_LIGHTGBM_PACKAGE=gpu_kernel_lightgbm_v11
  local BK_GPU_LIGHTGBM_MODEL_VERSION=1.1
  local result prediction path
  result=$(bk_section_package_transform_gpu_kernel_lightgbm_v10 "$@") || return 1
  prediction=$(jq -r '.artifacts[]? | select(.kind == "gpu_lightgbm_prediction_csv") | .path' <<< "$result")
  for path in "$prediction.input.csv" "$prediction.features.csv" "$prediction.validation.json"; do
    if [[ -f "$path" ]]; then
      result=$(jq -c --arg path "$path" '.artifacts += [{kind: "gpu_lightgbm_v11_evidence", path: $path}]' <<< "$result") || return 1
    fi
  done
  if [[ -f "$prediction.validation.json" ]]; then
    result=$(jq -c --slurpfile report "$prediction.validation.json" \
      '.metrics.profile_sample = $report[0]' <<< "$result") || return 1
  fi
  printf '%s\n' "$result"
}

# Model-specific job binding, shared by any application with scoped NCU inputs.
bk_section_package_run_job_gpu_kernel_lightgbm_v11() {
  local job="$1" output="$2" variable
  while IFS= read -r variable; do
    case "$variable" in
      BK_GPU_LIGHTGBM_INPUT_CSV*|BK_GPU_LIGHTGBM_PREDICTION_CSV*|BK_GPU_LIGHTGBM_NCU_ARCHIVE*|BK_GPU_LIGHTGBM_METADATA_JSON*)
        [[ -z "${!variable}" ]] || { echo "Conflicting bundle override: $variable" >&2; return 2; } ;;
    esac
  done < <(compgen -A variable BK_GPU_LIGHTGBM_)
  BK_GPU_LIGHTGBM_NCU_ARCHIVE=$(jq -er .archive <<< "$job") \
  BK_GPU_LIGHTGBM_METADATA_JSON=$(jq -er .metadata <<< "$job") \
  BK_GPU_LIGHTGBM_OUTPUT_DIR="$output" \
    bk_section_package_transform_gpu_kernel_lightgbm_v11 "$(jq -c .item <<< "$job")" 1 1 1 section
}

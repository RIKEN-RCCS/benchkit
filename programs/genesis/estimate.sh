#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint and run-time section metadata.

genesis_declare_estimation_layout() {
  bk_clear_estimation_defaults
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system "${BK_ESTIMATION_BASELINE_SYSTEM:-MiyabiG}"
  bk_define_baseline_exp "${BK_ESTIMATION_BASELINE_EXP:-${BK_GENESIS_EXP:-p8}}"
  bk_define_future_system "${BK_ESTIMATION_FUTURE_SYSTEM:-GPU_MLP_TARGET}"
  bk_define_current_target_nodes "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}"
  bk_define_future_target_nodes "${BK_ESTIMATION_FUTURE_TARGET_NODES:-1}"
  bk_declare_section --side future gpu_kernel_region gpu_kernel_mlp_v15
}

genesis_emit_estimation_data_from_fom() {
  local fom="$1"
  local artifact_path="results/padata0.tgz"
  local padata_path="$artifact_path"

  case "${BK_GENESIS_GPU_MLP_PROFILE:-false}" in
    1|true|TRUE|yes|YES|on|ON) ;;
    *) return 0 ;;
  esac

  if [[ -n "${GENESIS_BENCHKIT_ROOT:-}" ]]; then
    padata_path="${GENESIS_BENCHKIT_ROOT}/${artifact_path}"
  fi
  if [[ ! -f "$padata_path" ]]; then
    echo "Genesis GPU MLP estimation requested but profiler archive was not found: ${padata_path}" >&2
    return 0
  fi

  bk_emit_declared_section --side future gpu_kernel_region "$fom" "$artifact_path"
}

source scripts/bk_functions.sh
source scripts/estimation/common.sh

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-1.0}"
BK_GPU_MLP_ARTIFACT_MODE="${BK_GPU_MLP_ARTIFACT_MODE:-ncu}"
BK_GPU_MLP_SOURCE_GPU="${BK_GPU_MLP_SOURCE_GPU:-H100}"
BK_GPU_MLP_KERNEL_COUNT="${BK_GPU_MLP_KERNEL_COUNT:-20}"
export BK_GPU_MLP_ARTIFACT_MODE
export BK_GPU_MLP_SOURCE_GPU
export BK_GPU_MLP_KERNEL_COUNT

genesis_declare_estimation_layout
bk_estimation_apply_declared_defaults
BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0 2>/dev/null || exit 0
fi

BK_ESTIMATION_INPUT_JSON="$1"

bk_estimation_run_declared_future_package "$BK_ESTIMATION_INPUT_JSON"
bk_estimation_run_recorded_current_with_weakscaling \
  "${BK_ESTIMATION_BASELINE_SYSTEM:-MiyabiG}" \
  "${BK_ESTIMATION_BASELINE_EXP:-}" \
  "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}" \
  "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"

bk_estimation_write_output "results/estimate_${est_code}_0.json"

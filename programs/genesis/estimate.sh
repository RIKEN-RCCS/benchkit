#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint and run-time section metadata.

genesis_gpu_section_packages() {
  local raw=""

  if [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGES:-}" ]]; then
    raw="$BK_GENESIS_GPU_SECTION_PACKAGES"
  elif [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGE:-}" ]]; then
    raw="$BK_GENESIS_GPU_SECTION_PACKAGE"
  else
    raw="gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15"
  fi

  printf '%s\n' "$raw" |
    tr ',' '\n' |
    awk '{
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      if ($0 != "") print $0
    }'
}

genesis_primary_gpu_section_package() {
  genesis_gpu_section_packages | head -n 1
}

genesis_declare_estimation_layout() {
  local gpu_section_package="${BK_GENESIS_GPU_SECTION_PACKAGE:-}"

  if [[ -z "$gpu_section_package" ]]; then
    gpu_section_package=$(genesis_primary_gpu_section_package)
  fi

  bk_clear_estimation_defaults
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system "${BK_ESTIMATION_BASELINE_SYSTEM:-MiyabiG}"
  bk_define_baseline_exp "${BK_ESTIMATION_BASELINE_EXP:-${BK_GENESIS_EXP:-p8}}"
  bk_define_future_system "${BK_ESTIMATION_FUTURE_SYSTEM:-GPU_MLP_TARGET}"
  bk_define_current_target_nodes "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}"
  bk_define_future_target_nodes "${BK_ESTIMATION_FUTURE_TARGET_NODES:-1}"
  bk_declare_section --side future gpu_kernel_region "$gpu_section_package"
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

genesis_write_estimation_input_for_gpu_package() {
  local input_json="$1"
  local gpu_section_package="$2"
  local output_json="$3"

  jq \
    --arg package "$gpu_section_package" '
      if (.fom_breakdown.sections? // null) == null then
        .
      else
        .fom_breakdown.sections |= map(
          if (.name // "") == "gpu_kernel_region" then
            .estimation_package = $package
          else
            .
          end
        )
      end
    ' "$input_json" > "$output_json"
}

source scripts/bk_functions.sh
source scripts/estimation/common.sh

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-1.0}"
BK_GPU_MLP_ARTIFACT_MODE="${BK_GPU_MLP_ARTIFACT_MODE:-ncu}"
BK_GPU_MLP_SOURCE_GPU="${BK_GPU_MLP_SOURCE_GPU:-H100}"
BK_GPU_MLP_KERNEL_COUNT="${BK_GPU_MLP_KERNEL_COUNT:-20}"
BK_GPU_LIGHTGBM_ARTIFACT_MODE="${BK_GPU_LIGHTGBM_ARTIFACT_MODE:-ncu}"
BK_GPU_LIGHTGBM_SOURCE_GPU="${BK_GPU_LIGHTGBM_SOURCE_GPU:-${BK_GPU_MLP_SOURCE_GPU}}"
export BK_GPU_MLP_ARTIFACT_MODE
export BK_GPU_MLP_SOURCE_GPU
export BK_GPU_MLP_KERNEL_COUNT
export BK_GPU_LIGHTGBM_ARTIFACT_MODE
export BK_GPU_LIGHTGBM_SOURCE_GPU

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  return 0 2>/dev/null || exit 0
fi

genesis_run_single_estimate() {
  local input_json="$1"
  local output_index="$2"

  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"

  BK_ESTIMATION_INPUT_JSON="$input_json"

  BK_ESTIMATION_SKIP_TOP_LEVEL_CURRENT_BREAKDOWN=true \
    bk_estimation_run_declared_future_package "$BK_ESTIMATION_INPUT_JSON"
  bk_estimation_run_recorded_current_with_weakscaling \
    "${BK_ESTIMATION_BASELINE_SYSTEM:-MiyabiG}" \
    "${BK_ESTIMATION_BASELINE_EXP:-}" \
    "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}" \
    "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"

  bk_estimation_write_output "results/estimate_${est_code}_${output_index}.json"
}

genesis_run_estimates_for_gpu_packages() {
  local input_json="$1"
  local output_index=0
  local gpu_section_package
  local package_input_json
  local packages=()

  mapfile -t packages < <(genesis_gpu_section_packages)
  if (( ${#packages[@]} == 0 )); then
    echo "ERROR: no GENESIS GPU section packages were selected" >&2
    return 1
  fi

  mkdir -p results
  for gpu_section_package in "${packages[@]}"; do
    echo "Running GENESIS GPU estimation package: ${gpu_section_package}"
    package_input_json=$(mktemp "${TMPDIR:-/tmp}/benchkit-genesis-estimate-${gpu_section_package}.XXXXXX.json")
    genesis_write_estimation_input_for_gpu_package \
      "$input_json" \
      "$gpu_section_package" \
      "$package_input_json"
    if ! BK_GENESIS_GPU_SECTION_PACKAGE="$gpu_section_package" \
      BK_GENESIS_GPU_SECTION_PACKAGES="" \
      BK_GENESIS_ESTIMATE_OUTPUT_INDEX="$output_index" \
      bash "$0" "$package_input_json"; then
      rm -f "$package_input_json"
      return 1
    fi
    rm -f "$package_input_json"
    output_index=$((output_index + 1))
  done
}

BK_ESTIMATION_INPUT_JSON="$1"

if [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGE:-}" && -z "${BK_GENESIS_GPU_SECTION_PACKAGES:-}" ]]; then
  genesis_run_single_estimate "$BK_ESTIMATION_INPUT_JSON" "${BK_GENESIS_ESTIMATE_OUTPUT_INDEX:-0}"
else
  genesis_run_estimates_for_gpu_packages "$BK_ESTIMATION_INPUT_JSON"
fi

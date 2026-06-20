#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint.

source scripts/bk_functions.sh
source scripts/estimation/common.sh
source programs/genesis/sections.sh

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-1.0}"
BK_GENESIS_GPU_TARGET_GPU="${BK_GENESIS_GPU_TARGET_GPU:-GB200}"
bk_estimation_configure_gpu_kernel_defaults \
  H100 \
  "$BK_GENESIS_GPU_TARGET_GPU" \
  "" \
  20 \
  ncu
bk_estimation_configure_gpu_kernel_section_regexes "$(cat <<'EOF'
pairlist|build_pairlist
pme_real_inter|force_inter_cell
pme_real_intra|force_intra_cell
EOF
)"

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  return 0 2>/dev/null || exit 0
fi

genesis_run_single_estimate() {
  local input_json="$1"
  local output_index="$2"
  local package_input_json="$input_json"
  local synthetic_breakdown=0

  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  if ! bk_estimation_input_has_fom_breakdown "$input_json"; then
    package_input_json=$(mktemp "${TMPDIR:-/tmp}/benchkit-genesis-total-breakdown.XXXXXX.json")
    bk_estimation_write_total_identity_breakdown_input "$input_json" "$package_input_json"
    synthetic_breakdown=1
  fi

  BK_ESTIMATION_INPUT_JSON="$package_input_json"

  BK_ESTIMATION_SKIP_TOP_LEVEL_CURRENT_BREAKDOWN=true \
    bk_estimation_run_declared_future_package "$BK_ESTIMATION_INPUT_JSON"
  bk_estimation_run_recorded_current_with_weakscaling \
    "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}" \
    "${BK_ESTIMATION_BASELINE_EXP:-}" \
    "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}" \
    "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"
  est_current_fom="${est_current_bench_fom:-$est_current_fom}"

  if [[ "$synthetic_breakdown" -eq 1 ]]; then
    bk_estimation_mark_gpu_section_time_missing "GENESIS"
    rm -f "$package_input_json"
  fi

  bk_estimation_write_output "results/estimate_${est_code}_${output_index}.json"
}

BK_ESTIMATION_INPUT_JSON="$1"
genesis_run_single_estimate "$BK_ESTIMATION_INPUT_JSON" "${BK_GENESIS_ESTIMATE_OUTPUT_INDEX:-0}"

#!/bin/bash
# estimate.sh — Reference package-based estimation entrypoint for qws

qws_declare_estimation_layout() {
  bk_clear_estimation_defaults
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system Fugaku
  bk_define_baseline_exp CASE0
  bk_define_future_system FugakuNEXT
  bk_define_current_target_nodes 1024
  bk_define_future_target_nodes 256
  bk_declare_section --side future prepare_rhs half
  bk_declare_section --side future compute_hopping quarter
  bk_declare_section --side future compute_solver half
  bk_declare_section --side future halo_exchange quarter
  bk_declare_section --side future allreduce logp
  bk_declare_section --side future write_result half
  bk_declare_overlap --side future compute_hopping,halo_exchange half
}

qws_create_dummy_estimation_artifact() {
  local rel_path="$1"
  local content="$2"
  local full_path="results/${rel_path}"
  mkdir -p "$(dirname "$full_path")"
  printf '%s\n' "$content" > "$full_path"
}

qws_emit_estimation_data_from_fom() {
  local fom="$1"
  local section_prepare_rhs
  local section_compute_hopping
  local section_compute_solver
  local section_halo_exchange
  local section_allreduce
  local section_write_result
  local overlap_compute_halo

  section_prepare_rhs=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.16}')
  section_compute_hopping=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.28}')
  section_compute_solver=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.18}')
  section_halo_exchange=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.18}')
  section_allreduce=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.16}')
  section_write_result=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.08}')
  overlap_compute_halo=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.04}')

  qws_create_dummy_estimation_artifact "estimation_inputs/prepare_rhs_interval.json" "{\"section\":\"prepare_rhs\",\"kind\":\"interval_time\"}"
  qws_create_dummy_estimation_artifact "estimation_inputs/compute_hopping_papi.tgz" "dummy papi archive for compute_hopping"
  qws_create_dummy_estimation_artifact "estimation_inputs/compute_solver_papi.tgz" "dummy papi archive for compute_solver"
  qws_create_dummy_estimation_artifact "estimation_inputs/halo_exchange_trace.tgz" "dummy mpi trace archive for halo_exchange"
  qws_create_dummy_estimation_artifact "estimation_inputs/allreduce_trace.tgz" "dummy collective trace archive for allreduce"
  qws_create_dummy_estimation_artifact "estimation_inputs/write_result_interval.json" "{\"section\":\"write_result\",\"kind\":\"interval_time\"}"
  qws_create_dummy_estimation_artifact "estimation_inputs/compute_halo_overlap.json" "{\"overlap\":[\"compute_hopping\",\"halo_exchange\"],\"kind\":\"overlap_time\"}"

  bk_emit_declared_section --side future prepare_rhs "$section_prepare_rhs" results/estimation_inputs/prepare_rhs_interval.json
  bk_emit_declared_section --side future compute_hopping "$section_compute_hopping" results/estimation_inputs/compute_hopping_papi.tgz
  bk_emit_declared_section --side future compute_solver "$section_compute_solver" results/estimation_inputs/compute_solver_papi.tgz
  bk_emit_declared_section --side future halo_exchange "$section_halo_exchange" results/estimation_inputs/halo_exchange_trace.tgz
  bk_emit_declared_section --side future allreduce "$section_allreduce" results/estimation_inputs/allreduce_trace.tgz
  bk_emit_declared_section --side future write_result "$section_write_result" results/estimation_inputs/write_result_interval.json
  bk_emit_declared_overlap --side future compute_hopping,halo_exchange "$overlap_compute_halo" results/estimation_inputs/compute_halo_overlap.json
}

source scripts/bk_functions.sh
source scripts/estimation/common.sh

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-0.5}"
BK_ESTIMATION_LOGP_SECTION_NAME="${BK_ESTIMATION_LOGP_SECTION_NAME:-allreduce}"
BK_ESTIMATION_INPUT_JSON="$1"

qws_declare_estimation_layout
bk_estimation_apply_declared_defaults
BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0 2>/dev/null || exit 0
fi

bk_estimation_run_declared_future_package "$BK_ESTIMATION_INPUT_JSON"
bk_estimation_run_recorded_current_with_weakscaling \
  "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}" \
  "${BK_ESTIMATION_BASELINE_EXP:-CASE0}" \
  "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1024}" \
  "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"

bk_estimation_write_output "results/estimate_${est_code}_0.json"

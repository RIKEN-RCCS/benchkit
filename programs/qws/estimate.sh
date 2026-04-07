#!/bin/bash
# estimate.sh — Reference package-based estimation entrypoint for qws

qws_declare_estimation_layout() {
  bk_clear_estimation_declarations
  bk_declare_section prepare_rhs identity
  bk_declare_section compute_hopping counter_papi_detailed
  bk_declare_section compute_solver counter_papi_detailed
  bk_declare_section halo_exchange trace_mpi_basic
  bk_declare_section allreduce logp
  bk_declare_section write_result identity
  bk_declare_overlap compute_hopping,halo_exchange overlap_max_basic
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

  bk_emit_declared_section prepare_rhs "$section_prepare_rhs" results/estimation_inputs/prepare_rhs_interval.json
  bk_emit_declared_section compute_hopping "$section_compute_hopping" results/estimation_inputs/compute_hopping_papi.tgz
  bk_emit_declared_section compute_solver "$section_compute_solver" results/estimation_inputs/compute_solver_papi.tgz
  bk_emit_declared_section halo_exchange "$section_halo_exchange" results/estimation_inputs/halo_exchange_trace.tgz
  bk_emit_declared_section allreduce "$section_allreduce" results/estimation_inputs/allreduce_trace.tgz
  bk_emit_declared_section write_result "$section_write_result" results/estimation_inputs/write_result_interval.json
  bk_emit_declared_overlap compute_hopping,halo_exchange "$overlap_compute_halo" results/estimation_inputs/compute_halo_overlap.json
}

source scripts/bk_functions.sh
source scripts/estimation/common.sh

BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-instrumented_app_sections_dummy}"
BK_ESTIMATION_BASELINE_SYSTEM="Fugaku"
BK_ESTIMATION_BASELINE_EXP="CASE0"
BK_ESTIMATION_FUTURE_SYSTEM="FugakuNEXT"
BK_ESTIMATION_CURRENT_TARGET_NODES="${BK_ESTIMATION_CURRENT_TARGET_NODES:-1024}"
BK_ESTIMATION_FUTURE_TARGET_NODES="${BK_ESTIMATION_FUTURE_TARGET_NODES:-256}"
BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-0.5}"
BK_ESTIMATION_LOGP_SECTION_NAME="${BK_ESTIMATION_LOGP_SECTION_NAME:-allreduce}"
BK_ESTIMATION_INPUT_JSON="$1"

qws_declare_estimation_layout

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0 2>/dev/null || exit 0
fi

load_estimation_package() {
  local package_name="$1"

  source "scripts/estimation/packages/${package_name}.sh"
  BK_ESTIMATION_PACKAGE_VERSION=$(bk_estimation_package_metadata | jq -r '.version // empty')
  case "$package_name" in
    weakscaling)
      BK_ESTIMATION_MODEL_NAME="weakscaling"
      BK_ESTIMATION_MODEL_VERSION="0.1"
      ;;
    instrumented_app_sections_dummy)
      BK_ESTIMATION_MODEL_NAME="instrumented-app-sections-dummy"
      BK_ESTIMATION_MODEL_VERSION="0.1"
      ;;
    *)
      echo "ERROR: Unsupported estimation package for qws: ${package_name}" >&2
      exit 1
      ;;
  esac
}

load_estimation_package "$BK_ESTIMATION_PACKAGE"

read_values "$BK_ESTIMATION_INPUT_JSON"

if ! bk_estimation_execute_with_fallback load_estimation_package; then
  echo "ERROR: estimation package ${BK_ESTIMATION_PACKAGE} is not applicable for input ${BK_ESTIMATION_INPUT_JSON}" >&2
  exit 1
fi

mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"

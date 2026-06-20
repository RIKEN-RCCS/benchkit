#!/bin/bash
# estimate.sh — Reference package-based estimation entrypoint for qws

qws_repo_root() {
  if [[ -f programs/qws/estimate.sh ]]; then
    printf '.\n'
  elif [[ -f ../programs/qws/estimate.sh ]]; then
    printf '..\n'
  else
    printf '.\n'
  fi
}

qws_results_dir() {
  local root

  root=$(qws_repo_root)
  if [[ "$root" == "." ]]; then
    printf 'results\n'
  else
    printf '%s/results\n' "$root"
  fi
}

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
  bk_declare_estimation_items --side future "$(cat <<'EOF'
section|prepare_rhs|half
section|compute_hopping|quarter
section|compute_solver|half
section|halo_exchange|quarter
section|allreduce|logp
section|write_result|half
overlap|compute_hopping,halo_exchange|half
EOF
)"
}

qws_create_dummy_estimation_artifact() {
  local rel_path="$1"
  local content="$2"
  local full_path

  full_path="$(qws_results_dir)/${rel_path}"
  mkdir -p "$(dirname "$full_path")"
  printf '%s\n' "$content" > "$full_path"
}

qws_emit_estimation_data_from_fom() {
  local fom="$1"

  qws_create_dummy_estimation_artifact "estimation_artifacts/prepare_rhs_interval.json" "{\"section\":\"prepare_rhs\",\"kind\":\"interval_time\"}"
  qws_create_dummy_estimation_artifact "estimation_artifacts/compute_hopping_papi.tgz" "dummy papi archive for compute_hopping"
  qws_create_dummy_estimation_artifact "estimation_artifacts/compute_solver_papi.tgz" "dummy papi archive for compute_solver"
  qws_create_dummy_estimation_artifact "estimation_artifacts/halo_exchange_trace.tgz" "dummy mpi trace archive for halo_exchange"
  qws_create_dummy_estimation_artifact "estimation_artifacts/allreduce_trace.tgz" "dummy collective trace archive for allreduce"
  qws_create_dummy_estimation_artifact "estimation_artifacts/write_result_interval.json" "{\"section\":\"write_result\",\"kind\":\"interval_time\"}"
  qws_create_dummy_estimation_artifact "estimation_artifacts/compute_halo_overlap.json" "{\"overlap\":[\"compute_hopping\",\"halo_exchange\"],\"kind\":\"overlap_time\"}"

  bk_emit_declared_fractional_items --side future "$fom" "$(cat <<'EOF'
section|prepare_rhs|0.16|results/estimation_artifacts/prepare_rhs_interval.json
section|compute_hopping|0.28|results/estimation_artifacts/compute_hopping_papi.tgz
section|compute_solver|0.18|results/estimation_artifacts/compute_solver_papi.tgz
section|halo_exchange|0.18|results/estimation_artifacts/halo_exchange_trace.tgz
section|allreduce|0.16|results/estimation_artifacts/allreduce_trace.tgz
section|write_result|0.08|results/estimation_artifacts/write_result_interval.json
overlap|compute_hopping,halo_exchange|0.04|results/estimation_artifacts/compute_halo_overlap.json
EOF
)"
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

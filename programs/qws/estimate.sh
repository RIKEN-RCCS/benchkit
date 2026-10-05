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

qws_estimation_enabled() {
  local root

  root=$(qws_repo_root)
  [[ ! -f "${root}/programs/qws/estimate.disabled" ]]
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

# Keep estimation disabled until measured sections, overlap semantics and
# a suitable estimation package have been reviewed together.

if ! qws_estimation_enabled; then
  echo "QWS estimation is disabled until real section timings and artifacts are available." >&2
  if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0 2>/dev/null || exit 0
  fi
  exit 0
fi

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

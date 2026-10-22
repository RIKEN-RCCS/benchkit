#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/shell_test_parts.sh"
ALL_GROUPS=(common-observation-profiler common-observation-other common-execution-run common-execution-other result-sender estimation)

usage() {
  cat <<'EOF'
Usage: bash scripts/tests/run_profile_data_shell_tests.sh [all|common|common-observation|common-observation-profiler|common-observation-other|common-execution|common-execution-run|common-execution-other|result-sender|estimation|list|list-tests [GROUP]|list-cases [GROUP]] [--jobs 1|2]

Runs the shell tests covered by the Result Server Tests workflow.
Use "all" locally for the full suite, "common" for both common groups,
"common-observation" or "common-execution" for both parts, or a CI group name.
EOF
}

check_dependencies() {
  command -v jq
  jq --version
  command -v python3
  python3 --version

  local estimation_python=""
  local candidate
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      estimation_python=$(command -v "$candidate")
      break
    fi
  done
  test -n "$estimation_python"
  "$estimation_python" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

tests_for_group() {
  case "$1" in
    common)
      tests_for_group common-observation
      tests_for_group common-execution
      ;;
    common-observation)
      tests_for_group common-observation-profiler
      tests_for_group common-observation-other
      ;;
    common-observation-profiler)
      echo scripts/tests/test_bk_profiler.sh
      ;;
    common-observation-other)
      cat <<'EOF'
scripts/tests/test_workflow_timing.sh
scripts/tests/test_bk_timing_observations.sh
scripts/tests/test_ncu_plan_generation.sh
scripts/tests/test_sbd_ncu_profile.sh
EOF
      ;;
    common-execution)
      tests_for_group common-execution-run
      tests_for_group common-execution-other
      ;;
    common-execution-run)
      echo scripts/tests/test_bk_run.sh
      ;;
    common-execution-other)
      cat <<'EOF'
scripts/tests/test_run_benchmark.sh
scripts/tests/test_bk_fetch_source.sh
scripts/tests/test_bk_input_info.sh
scripts/tests/test_qws_timing_artifact.sh
scripts/tests/test_rc_app_environments.sh
scripts/tests/test_build_environment_snapshot.sh
scripts/tests/test_flow2_cpu_sbd.sh
scripts/tests/test_sbd_rikyu.sh
scripts/tests/test_compute_snapshot_dependencies.sh
scripts/tests/test_node_status_snapshot.sh
scripts/tests/test_ci_timing_context.sh
scripts/tests/test_scheduler_extra_args.sh
scripts/tests/test_matrix_generate_filters.sh
EOF
      ;;
    result-sender)
      cat <<'EOF'
scripts/tests/test_build_cache.sh
scripts/tests/test_result_profile_data.sh
scripts/tests/test_process_and_send_results.sh
scripts/tests/test_result_common_json_contract.sh
scripts/tests/test_send_results_profile_data.sh
scripts/tests/test_send_estimate_artifacts.sh
EOF
      ;;
    estimation)
      cat <<'EOF'
scripts/tests/test_estimation_common_json_contract.sh
scripts/tests/test_estimation_run_timing.sh
scripts/tests/test_estimation_input_restoration.sh
scripts/tests/test_estimation_gpu_kernel_ensemble_average.sh
scripts/tests/test_estimation_gpu_kernel_lightgbm_v10.sh
scripts/tests/test_estimation_gpu_kernel_lightgbm_v11.sh
scripts/tests/test_estimation_gpu_kernel_mlp_v15.sh
scripts/tests/test_genesis_gpu_mlp_estimation.sh
scripts/tests/test_sbd_davidson_ratio.sh
EOF
      ;;
    all)
      local group
      for group in "${ALL_GROUPS[@]}"; do
        tests_for_group "$group"
      done
      ;;
    *)
      echo "Unknown shell test group: $1" >&2
      usage >&2
      return 2
      ;;
  esac
}

run_one_test() {
  local test_rel="$1"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::group::${test_rel}"
  else
    echo "==> ${test_rel}"
  fi
  bash "${REPO_DIR}/${test_rel}"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::endgroup::"
  fi
}

cases_for_group() {
  local test_rel part parts selection
  selection=$(tests_for_group "$1") || return $?
  while IFS= read -r test_rel; do
    if parts=$(shell_test_parts "$test_rel"); then
      while IFS= read -r part; do printf '%s::%s\n' "$test_rel" "$part"; done <<< "$parts"
    else
      printf '%s\n' "$test_rel"
    fi
  done <<< "$selection"
}

run_group() {
  local group="$1" jobs="${2:-1}" selection test_rel case_id part
  selection=$(tests_for_group "$group") || return $?
  check_dependencies
  if [ "$jobs" = 1 ]; then
    local count=0
    while IFS= read -r test_rel; do
      [ -f "${REPO_DIR}/${test_rel}" ] || { echo "Missing shell test: $test_rel" >&2; return 1; }
      run_one_test "$test_rel"
      count=$((count + 1))
    done <<< "$selection"
    [ "$count" -gt 0 ] || return 1
    echo "Ran ${count} shell test(s) for group: ${group}"
    return 0
  fi
  [ "$jobs" = 2 ] || { echo 'Expected --jobs 1 or 2' >&2; return 2; }
  local selection_cases cases=()
  selection_cases=$(cases_for_group "$group") || return $?
  mapfile -t cases <<< "$selection_cases"
  python3 "${SCRIPT_DIR}/run_shell_test_cases.py" "$REPO_DIR" "${cases[@]}"

}

main() {
  local group="${1:-all}"
  case "$group" in
    -h|--help)
      usage
      ;;
    list|--list)
      printf '%s\n' "${ALL_GROUPS[@]}"
      ;;
    list-tests|--list-tests)
      tests_for_group "${2:-all}"
      ;;
    list-cases)
      cases_for_group "${2:-all}"
      ;;
    *)
      if [ "$#" -gt 1 ] && { [ "$#" -ne 3 ] || [ "$2" != --jobs ]; }; then
        usage >&2; return 2
      fi
      run_group "$group" "${3:-1}"
      ;;
  esac
}

main "$@"

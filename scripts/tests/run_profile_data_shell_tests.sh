#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ALL_GROUPS=(common result-sender estimation)

usage() {
  cat <<'EOF'
Usage: bash scripts/tests/run_profile_data_shell_tests.sh [all|common|result-sender|estimation|list|list-tests [GROUP]]

Runs the shell tests covered by the Result Server Tests workflow.
Use "all" locally for the full suite, or a group name in CI matrix jobs.
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
      cat <<'EOF'
scripts/tests/test_bk_profiler.sh
scripts/tests/test_bk_fetch_source.sh
scripts/tests/test_bk_input_info.sh
scripts/tests/test_bk_timing_observations.sh
scripts/tests/test_qws_timing_artifact.sh
scripts/tests/test_build_environment_snapshot.sh
scripts/tests/test_node_status_snapshot.sh
scripts/tests/test_ci_timing_context.sh
scripts/tests/test_ncu_plan_generation.sh
scripts/tests/test_sbd_ncu_profile.sh
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
scripts/tests/test_estimation_gpu_kernel_ensemble_average.sh
scripts/tests/test_estimation_gpu_kernel_lightgbm_v10.sh
scripts/tests/test_estimation_gpu_kernel_mlp_v15.sh
scripts/tests/test_genesis_gpu_mlp_estimation.sh
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

run_group() {
  local group="$1"
  local count=0
  local test_rel

  check_dependencies
  while IFS= read -r test_rel; do
    [ -n "$test_rel" ] || continue
    if [ ! -f "${REPO_DIR}/${test_rel}" ]; then
      echo "Missing shell test: ${test_rel}" >&2
      return 1
    fi
    run_one_test "$test_rel"
    count=$((count + 1))
  done < <(tests_for_group "$group")

  if [ "$count" -eq 0 ]; then
    echo "No shell tests selected for group: ${group}" >&2
    return 1
  fi
  echo "Ran ${count} shell test(s) for group: ${group}"
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
    *)
      run_group "$group"
      ;;
  esac
}

main "$@"

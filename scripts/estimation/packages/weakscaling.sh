#!/bin/bash
# weakscaling.sh - Reference estimation package for same-line weak scaling

# shellcheck disable=SC1091
source scripts/estimation/packages/top_level_package_common.sh

bk_estimation_package_metadata() {
  cat "${BASH_SOURCE[0]%/*}/weakscaling.metadata.json"
}

bk_estimation_package_check_applicability() {
  local current_system="${BK_ESTIMATION_CURRENT_SYSTEM:-$est_system}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-$est_system}"
  local missing_inputs=()

  if [[ -z "${est_fom:-}" ]]; then
    missing_inputs+=('"fom"')
  fi
  if [[ -z "${est_input_fom_breakdown:-}" || "${est_input_fom_breakdown:-}" == "null" ]]; then
    missing_inputs+=('"fom_breakdown"')
  fi

  if (( ${#missing_inputs[@]} > 0 )); then
    local missing_inputs_json
    missing_inputs_json="[$(IFS=,; echo "${missing_inputs[*]}")]"
    bk_estimation_set_applicability "needs_remeasurement" "" "$missing_inputs_json" '["provide-section-breakdown-for-weakscaling"]'
    return 1
  fi

  if ! bk_estimation_validate_system_relation "intra_system_scaling_model" "$est_system" "$current_system" "same_system_line"; then
    bk_estimation_set_applicability "not_applicable" "" '[]' '["use-a-same-line-current-system"]' '["current_system_relation:same_system_line_required"]'
    return 1
  fi

  if ! bk_estimation_validate_system_relation "intra_system_scaling_model" "$est_system" "$future_system" "same_system_line"; then
    bk_estimation_set_applicability "not_applicable" "" '[]' '["use-a-same-line-target-system"]' '["target_system_relation:same_system_line_required"]'
    return 1
  fi

  bk_estimation_set_applicability "applicable"
  return 0
}

_bk_weakscaling_normalize_breakdown_packages() {
  local breakdown_json="$1"

  echo "$breakdown_json" | jq -c '
    .
    | .sections = ((.sections // []) | map(
        if (.estimation_package // "") == "logp" then
          .
        else
          (. + {estimation_package: "identity"}
           | del(.requested_estimation_package, .fallback_used, .package_applicability, .scaling_method, .model, .metrics))
        end
      ))
    | .overlaps = ((.overlaps // []) | map(
        . + {estimation_package: "identity"}
        | del(.requested_estimation_package, .fallback_used, .package_applicability, .scaling_method, .model, .metrics)
      ))
  '
}

bk_estimation_package_normalize_recorded_current_breakdown() {
  _bk_weakscaling_normalize_breakdown_packages "$1"
}

bk_estimation_package_run() {
  local current_system="${BK_ESTIMATION_CURRENT_SYSTEM:-$est_system}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-$est_system}"
  local current_target_nodes="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
  local future_target_nodes="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"
  local model_name
  local applicability_issues_json

  model_name=$(bk_estimation_model_name_from_metadata "top_level" "weakscaling")

  est_current_system="$current_system"
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="$model_name"
  est_current_bench_system="$est_system"
  est_current_bench_fom="$est_fom"
  est_current_bench_nodes="$est_node_count"
  est_current_bench_numproc_node="$est_numproc_node"
  est_current_bench_timestamp="$est_timestamp"
  est_current_bench_uuid="$est_uuid"
  est_current_fom_breakdown=$(bk_top_level_transform_breakdown "$(_bk_weakscaling_normalize_breakdown_packages "$est_input_fom_breakdown")" "$current_target_nodes" "$est_node_count" "1" "identity" "identity")
  est_current_fom=$(bk_top_level_breakdown_total_time "$est_current_fom_breakdown")

  est_future_system="$future_system"
  est_future_target_nodes="$future_target_nodes"
  est_future_scaling_method="$model_name"
  est_future_bench_system="$est_system"
  est_future_bench_fom="$est_fom"
  est_future_bench_nodes="$est_node_count"
  est_future_bench_numproc_node="$est_numproc_node"
  est_future_bench_timestamp="$est_timestamp"
  est_future_bench_uuid="$est_uuid"
  est_future_fom_breakdown=$(bk_top_level_transform_breakdown "$(_bk_weakscaling_normalize_breakdown_packages "$est_input_fom_breakdown")" "$future_target_nodes" "$est_node_count" "1" "identity" "identity")
  est_future_fom=$(bk_top_level_breakdown_total_time "$est_future_fom_breakdown")

  applicability_issues_json=$(jq -cn \
    --argjson current "$(bk_top_level_collect_breakdown_package_issues "$est_current_fom_breakdown")" \
    --argjson future "$(bk_top_level_collect_breakdown_package_issues "$est_future_fom_breakdown")" \
    '$current + $future')
  bk_top_level_set_applicability_from_breakdowns \
    "$applicability_issues_json" \
    '["provide-section-times-or-use-supported-section-packages"]'

  bk_estimation_apply_package_output_defaults_from_metadata

  est_assumptions_json=$(bk_estimation_build_assumptions_json_from_metadata \
    "$current_system" \
    "$future_system" \
    "$current_target_nodes" \
    "$future_target_nodes" \
    "logp")

  est_model_json=$(bk_estimation_build_model_json_from_metadata \
    "top_level" \
    "" \
    "" \
    "section-wise" \
    "$model_name" \
    "" \
    "$model_version")
  est_current_model_json=$(bk_estimation_build_model_json_from_metadata \
    "current_system" \
    "$est_system" \
    "$current_system" \
    "intra_system_scaling_model" \
    "weakscaling-current" \
    "same_system_line" \
    "$model_version")
  est_future_model_json=$(bk_estimation_build_model_json_from_metadata \
    "future_system" \
    "$est_system" \
    "$future_system" \
    "intra_system_scaling_model" \
    "weakscaling-future" \
    "same_system_line" \
    "$model_version")

}

bk_estimation_package_build_recorded_current_model_json() {
  local baseline_system="$1"
  local model_version="$2"

  bk_estimation_build_model_json_from_metadata \
    "recorded_current" \
    "$baseline_system" \
    "$baseline_system" \
    "intra_system_scaling_model" \
    "weakscaling-current" \
    "same_system_line" \
    "$model_version"
}

bk_estimation_package_apply_metadata() {
  local package_version
  package_version=$(bk_estimation_package_metadata | jq -r '.version // "0.1"')

  bk_estimation_apply_package_metadata_from_definition "weakscaling"
  bk_estimation_set_current_package_metadata \
    "weakscaling" \
    "$package_version" \
    "${est_requested_estimation_package:-weakscaling}" \
    "${est_requested_estimation_package_version:-$package_version}"
  bk_estimation_set_future_package_metadata \
    "weakscaling" \
    "$package_version" \
    "${est_requested_estimation_package:-weakscaling}" \
    "${est_requested_estimation_package_version:-$package_version}"

  est_estimation_id="estimate-${est_code}-${est_uuid:-unknown}"
  est_estimation_timestamp=$(date '+%Y-%m-%d %H:%M:%S')
}

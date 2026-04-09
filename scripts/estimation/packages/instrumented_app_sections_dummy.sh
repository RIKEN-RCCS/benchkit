#!/bin/bash
# instrumented_app_sections_dummy.sh - Reference estimation package for
# application-defined section timings.

# shellcheck disable=SC1091
source scripts/estimation/packages/top_level_package_common.sh

bk_estimation_package_metadata() {
  cat <<'EOF'
{
  "name": "instrumented_app_sections_dummy",
  "version": "0.1",
  "method_class": "detailed",
  "detail_level": "intermediate",
  "required_inputs": {
    "mandatory": ["result_json", "fom", "fom_breakdown", "target_nodes_current", "target_nodes_future"],
    "optional": ["section_artifacts"],
    "external": []
  },
  "required_result_fields": [
    "code",
    "system",
    "fom",
    "fom_breakdown.sections",
    "target_nodes_current",
    "target_nodes_future"
  ],
  "supported_section_packages": [
    "identity",
    "half",
    "quarter",
    "counter_papi_detailed",
    "trace_mpi_basic",
    "logp"
  ],
  "supported_overlap_packages": [
    "half",
    "quarter",
    "overlap_max_basic"
  ],
  "output_fields": [
    "applicability",
    "current_system",
    "current_system.fom_breakdown",
    "future_system",
    "future_system.fom_breakdown",
    "performance_ratio",
    "estimate_metadata"
  ],
  "not_applicable_when": [
    "fom_breakdown is missing",
    "a bound item has no usable package",
    "a bound package and its fallback candidates are all unavailable"
  ],
  "fallback_policy": {
    "mode": "allowed",
    "target": "weakscaling"
  },
  "models": {
    "top_level": {
      "type": "section-wise",
      "name": "instrumented-app-sections-dummy"
    },
    "current_system": {
      "type": "intra_system_scaling_model",
      "name": "instrumented-app-sections-current-scaling",
      "system_compatibility_rule": "exact_match"
    },
    "future_system": {
      "type": "cross_system_projection_model",
      "name": "instrumented-app-sections-future-projection",
      "system_compatibility_rule": "cross_system_allowed"
    }
  },
  "defaults": {
    "measurement": {
      "tool": "application-section-timer",
      "method": "section-timing",
      "annotation_method": "app-defined-sections",
      "counter_set": null,
      "interval_timing_method": "measured"
    },
    "confidence": {
      "level": "experimental",
      "score": 0.20
    },
    "notes": {
      "summary": "Reference implementation for application-defined section timing based estimation in BenchKit."
    },
    "assumptions": {
      "scaling_assumption": "weak-scaling",
      "default_section_rule": "sections and overlaps are scaled according to their bound section package",
      "logp_section_rule_template": "sections bound to package {logp_package_name} are scaled with logP",
      "overlap_rule": "overlap timings are scaled according to their bound overlap package"
    }
  }
}
EOF
}

bk_estimation_package_check_applicability() {
  local missing_inputs=()
  local incompatibilities=()
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local missing_metadata

  if [[ -z "${est_fom:-}" ]]; then
    missing_inputs+=('"fom"')
  fi
  if [[ -z "${est_input_fom_breakdown:-}" || "${est_input_fom_breakdown:-}" == "null" ]]; then
    missing_inputs+=('"fom_breakdown"')
  fi

  if [[ -n "${est_input_fom_breakdown:-}" && "${est_input_fom_breakdown:-}" != "null" ]]; then
    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(bk_top_level_list_missing_bound_packages "$est_input_fom_breakdown")

    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(bk_top_level_list_unsupported_bound_packages "$est_input_fom_breakdown")

    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(bk_top_level_list_unrecoverable_bound_input_problems "$est_input_fom_breakdown")
  fi

  if ! bk_estimation_validate_system_relation \
    "cross_system_projection_model" \
    "${est_system:-}" \
    "$future_system" \
    "cross_system_allowed"; then
    incompatibilities+=('"future_system_cross_projection"')
  fi

  if ! bk_estimation_validate_system_relation \
    "intra_system_scaling_model" \
    "$baseline_system" \
    "$baseline_system" \
    "exact_match"; then
    incompatibilities+=('"current_system_intra_scaling"')
  fi

  if (( ${#missing_inputs[@]} > 0 )); then
    local missing_inputs_json
    missing_inputs_json="[$(IFS=,; echo "${missing_inputs[*]}")]"
    if bk_estimation_validate_system_relation \
      "intra_system_scaling_model" \
      "${est_system:-}" \
      "$future_system" \
      "same_system_line"; then
      bk_estimation_set_applicability \
        "fallback" \
        "weakscaling" \
        "$missing_inputs_json" \
        '["use-weakscaling-estimation-or-provide-section-breakdown"]'
    else
      bk_estimation_set_applicability \
        "not_applicable" \
        "" \
        "$missing_inputs_json" \
        '["provide-section-breakdown-for-cross-system-estimation"]'
    fi
    return 1
  fi

  if (( ${#incompatibilities[@]} > 0 )); then
    local incompatibilities_json
    incompatibilities_json="[$(IFS=,; echo "${incompatibilities[*]}")]"
    bk_estimation_set_applicability \
      "not_applicable" \
      "" \
      '[]' \
      '[]' \
      "$incompatibilities_json"
    return 1
  fi

  bk_estimation_set_applicability "applicable"
  return 0
}

_bk_logp_factor() {
  local target_nodes="$1"
  local bench_nodes="$2"

  awk -v target="$target_nodes" -v bench="$bench_nodes" '
    function safe_nodes(x) { return (x < 2 ? 2 : x) }
    function lg2(x) { return log(x) / log(2) }
    BEGIN {
      printf "%.12f", lg2(safe_nodes(target)) / lg2(safe_nodes(bench))
    }'
}

_bk_transform_bound_breakdown() {
  local breakdown_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  bk_top_level_transform_breakdown "$breakdown_json" "$target_nodes" "$bench_nodes" "$default_factor" "" ""
}

_bk_set_top_level_applicability_from_breakdowns() {
  local issues_json="$1"
  bk_top_level_set_applicability_from_breakdowns \
    "$issues_json" \
    '["provide-missing-section-inputs-or-enable-compatible-fallback"]'
}

bk_estimation_package_run() {
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local baseline_exp="${BK_ESTIMATION_BASELINE_EXP:-CASE0}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local current_target_nodes="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
  local future_target_nodes="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"
  local model_name
  local default_section_factor="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-0.5}"
  local logp_section_name="${BK_ESTIMATION_LOGP_SECTION_NAME:-allreduce}"
  local logp_package_name="logp"
  local breakdown_template
  local baseline_breakdown
  local applicability_issues_json

  model_name=$(bk_estimation_model_name_from_metadata "top_level" "instrumented-app-sections-dummy")

  est_future_bench_system="$est_system"
  est_future_bench_fom="$est_fom"
  est_future_bench_nodes="$est_node_count"
  est_future_bench_numproc_node="$est_numproc_node"
  est_future_bench_timestamp="$est_timestamp"
  est_future_bench_uuid="$est_uuid"

  est_current_system="$baseline_system"
  fetch_current_fom "$baseline_system" "$est_code" "$baseline_exp"
  baseline_breakdown="$est_current_fom_breakdown"
  if [[ -z "$baseline_breakdown" || "$baseline_breakdown" == "null" ]]; then
    baseline_breakdown="$est_input_fom_breakdown"
  elif ! echo "$baseline_breakdown" | jq -e --arg pkg "$logp_package_name" '.sections // [] | any((.estimation_package // "") == $pkg)' >/dev/null; then
    baseline_breakdown="$est_input_fom_breakdown"
  fi

  if [[ -n "$baseline_breakdown" && "$baseline_breakdown" != "null" ]]; then
    breakdown_template=$(bk_top_level_scale_breakdown_to_total "$baseline_breakdown" "$est_current_fom" "instrumented-app-sections-dummy")
    est_current_fom_breakdown=$(_bk_transform_bound_breakdown \
      "$breakdown_template" \
      "$current_target_nodes" \
      "${est_current_bench_nodes:-1}" \
      "$default_section_factor")
    est_current_fom_breakdown=$(bk_top_level_attach_default_package_name "$est_current_fom_breakdown" "instrumented_app_sections_dummy")
    est_current_fom=$(bk_top_level_breakdown_total_time "$est_current_fom_breakdown")
  fi
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="$model_name"

  est_future_system="$future_system"
  est_future_fom_breakdown=$(_bk_transform_bound_breakdown \
    "$est_input_fom_breakdown" \
    "$future_target_nodes" \
    "$est_node_count" \
    "$default_section_factor")
  est_future_fom_breakdown=$(bk_top_level_attach_default_package_name "$est_future_fom_breakdown" "instrumented_app_sections_dummy")
  est_future_fom=$(bk_top_level_breakdown_total_time "$est_future_fom_breakdown")
  est_future_target_nodes="$future_target_nodes"
  est_future_scaling_method="$model_name"

  applicability_issues_json=$(jq -cn \
    --argjson current "$(bk_top_level_collect_breakdown_package_issues "$est_current_fom_breakdown")" \
    --argjson future "$(bk_top_level_collect_breakdown_package_issues "$est_future_fom_breakdown")" \
    '$current + $future')
  _bk_set_top_level_applicability_from_breakdowns "$applicability_issues_json"

  bk_estimation_apply_package_output_defaults_from_metadata

  est_assumptions_json=$(bk_estimation_build_assumptions_json_from_metadata \
    "$baseline_system" \
    "$future_system" \
    "$current_target_nodes" \
    "$future_target_nodes" \
    "$logp_package_name" \
    "$logp_section_name")

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
    "$baseline_system" \
    "$baseline_system" \
    "intra_system_scaling_model" \
    "instrumented-app-sections-current-scaling" \
    "exact_match" \
    "$model_version")
  est_future_model_json=$(bk_estimation_build_model_json_from_metadata \
    "future_system" \
    "$est_system" \
    "$future_system" \
    "cross_system_projection_model" \
    "instrumented-app-sections-future-projection" \
    "cross_system_allowed" \
    "$model_version")

}

bk_estimation_package_apply_metadata() {
  local package_version
  package_version=$(bk_estimation_package_metadata | jq -r '.version // "0.1"')

  bk_estimation_apply_package_metadata_from_definition "instrumented_app_sections_dummy"
  bk_estimation_set_current_package_metadata \
    "instrumented_app_sections_dummy" \
    "$package_version" \
    "${est_requested_estimation_package:-instrumented_app_sections_dummy}" \
    "${est_requested_estimation_package_version:-$package_version}"
  bk_estimation_set_future_package_metadata \
    "instrumented_app_sections_dummy" \
    "$package_version" \
    "${est_requested_estimation_package:-instrumented_app_sections_dummy}" \
    "${est_requested_estimation_package_version:-$package_version}"

  est_estimation_id="estimate-${est_code}-${est_uuid:-unknown}"
  est_estimation_timestamp=$(date '+%Y-%m-%d %H:%M:%S')
}

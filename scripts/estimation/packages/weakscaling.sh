#!/bin/bash
# weakscaling.sh - Reference estimation package for same-line weak scaling

bk_estimation_package_metadata() {
  cat <<'EOF'
{
  "name": "weakscaling",
  "version": "0.1",
  "method_class": "lightweight",
  "detail_level": "basic",
  "required_inputs": {
    "mandatory": ["result_json", "fom", "fom_breakdown", "target_nodes_current", "target_nodes_future"],
    "optional": [],
    "external": []
  },
  "required_result_fields": [
    "code",
    "system",
    "fom",
    "fom_breakdown.sections"
  ],
  "supported_section_packages": [
    "identity",
    "logp"
  ],
  "supported_overlap_packages": [
    "identity"
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
    "target system is not on the same system line as the benchmark system",
    "a bound package and its fallback candidates are all unavailable"
  ],
  "fallback_policy": {
    "mode": "none",
    "target": null
  }
}
EOF
}

_bk_weakscaling_section_packages_loaded=0

_bk_weakscaling_load_section_package_impls() {
  local package_file

  if [[ "${_bk_weakscaling_section_packages_loaded}" == "1" ]]; then
    return 0
  fi

  for package_file in scripts/estimation/section_packages/*.sh; do
    [[ -f "$package_file" ]] || continue
    # shellcheck disable=SC1090
    source "$package_file"
  done

  _bk_weakscaling_section_packages_loaded=1
}

_bk_weakscaling_section_package_fallback_target() {
  local package_name="$1"
  local fn_name

  _bk_weakscaling_load_section_package_impls

  fn_name="bk_section_package_metadata_${package_name}"
  if declare -F "$fn_name" >/dev/null 2>&1; then
    "$fn_name" | jq -r '.fallback_target // empty'
    return 0
  fi

  echo ""
}

_bk_weakscaling_section_package_check_result() {
  local package_name="$1"
  local item_json="$2"
  local item_kind="$3"
  local fn_name

  _bk_weakscaling_load_section_package_impls

  fn_name="bk_section_package_check_applicability_${package_name}"
  if ! declare -F "$fn_name" >/dev/null 2>&1; then
    cat <<EOF
{"status":"not_applicable","missing_inputs":["${item_kind}_package_unsupported:${package_name}"]}
EOF
    return 1
  fi

  "$fn_name" "$item_json" "$item_kind"
}

_bk_weakscaling_dispatch_bound_item() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local item_kind="$4"
  local package_name
  local fn_name
  local fallback_target
  local check_result
  local missing_inputs_json

  package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
  if [[ -z "$package_name" ]]; then
    package_name="identity"
    item_json=$(echo "$item_json" | jq -c --arg package_name "$package_name" '. + {estimation_package: $package_name}')
  fi

  _bk_weakscaling_load_section_package_impls

  while true; do
    fn_name="bk_section_package_transform_${package_name}"
    check_result=$(_bk_weakscaling_section_package_check_result "$package_name" "$item_json" "$item_kind")
    if declare -F "$fn_name" >/dev/null 2>&1 && [[ "$(echo "$check_result" | jq -r '.status // "not_applicable"')" == "applicable" ]]; then
      "$fn_name" "$item_json" "$target_nodes" "$bench_nodes" "1" "$item_kind"
      return 0
    fi

    fallback_target=$(_bk_weakscaling_section_package_fallback_target "$package_name")
    if [[ -z "$fallback_target" || "$fallback_target" == "$package_name" ]]; then
      missing_inputs_json=$(echo "$check_result" | jq -c '.missing_inputs // []')
      echo "$item_json" | jq -c \
        --arg requested "$package_name" \
        --argjson missing_inputs "$missing_inputs_json" '
        .
        + {requested_estimation_package: (.requested_estimation_package // $requested)}
        + {time: null}
        + {scaling_method: "unresolved-package"}
        + {package_applicability: {status: "not_applicable", missing_inputs: $missing_inputs}}
      '
      return 0
    fi

    missing_inputs_json=$(echo "$check_result" | jq -c '.missing_inputs // []')
    item_json=$(echo "$item_json" | jq -c --arg requested "$package_name" --arg applied "$fallback_target" --argjson missing_inputs "$missing_inputs_json" '
      .
      + {requested_estimation_package: (.requested_estimation_package // $requested)}
      + {estimation_package: $applied}
      + {fallback_used: $applied}
      + {package_applicability: {status: "fallback", missing_inputs: $missing_inputs}}
    ')
    package_name="$fallback_target"
  done
}

_bk_weakscaling_transform_breakdown() {
  local breakdown_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local sections_out=()
  local overlaps_out=()
  local item_json

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    sections_out+=("$(_bk_weakscaling_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "section")")
  done < <(echo "$breakdown_json" | jq -c '.sections // [] | .[]')

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    overlaps_out+=("$(_bk_weakscaling_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "overlap")")
  done < <(echo "$breakdown_json" | jq -c '.overlaps // [] | .[]')

  jq -cn \
    --argjson sections "$(printf '%s\n' "${sections_out[@]}" | jq -s '.')" \
    --argjson overlaps "$(printf '%s\n' "${overlaps_out[@]}" | jq -s '.')" \
    '{sections: $sections, overlaps: $overlaps}'
}

_bk_weakscaling_breakdown_total_time() {
  local breakdown_json="$1"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  if echo "$breakdown_json" | jq -e '
    ((.sections // []) | any((.time // null) == null))
    or
    ((.overlaps // []) | any((.time // null) == null))
  ' >/dev/null 2>&1; then
    echo "null"
    return 0
  fi

  echo "$breakdown_json" | jq -r '
    (
      (.sections // [])
      | map(.time // .bench_time // 0)
      | add // 0
    ) - (
      (.overlaps // [])
      | map(.time // .bench_time // 0)
      | add // 0
    )
  '
}

_bk_weakscaling_collect_breakdown_package_issues() {
  local breakdown_json="$1"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo "[]"
    return 0
  fi

  echo "$breakdown_json" | jq -c '
    [
      ((.sections // [])
      | map(
          {
            item_kind: "section",
            item_name: .name,
            scaling_method: (.scaling_method // ""),
            package_status: (.package_applicability.status // ""),
            missing_inputs: (.package_applicability.missing_inputs // [])
          }
        )),
      ((.overlaps // [])
      | map(
          {
            item_kind: "overlap",
            item_name: (.sections | join(",")),
            scaling_method: (.scaling_method // ""),
            package_status: (.package_applicability.status // ""),
            missing_inputs: (.package_applicability.missing_inputs // [])
          }
        ))
    ] | add
  '
}

_bk_weakscaling_set_top_level_applicability() {
  local issues_json="$1"
  local has_not_applicable
  local has_fallback
  local aggregated_missing_inputs

  has_not_applicable=$(echo "$issues_json" | jq -r '
    any(
      (.scaling_method == "unresolved-package")
      or (.package_status == "not_applicable")
    )
  ')

  has_fallback=$(echo "$issues_json" | jq -r '
    any(.package_status == "fallback")
  ')

  aggregated_missing_inputs=$(echo "$issues_json" | jq -c '
    [
      .[]
      | select((.missing_inputs | length) > 0)
      | .missing_inputs[]
    ] | unique
  ')

  if [[ "$has_not_applicable" == "true" ]]; then
    bk_estimation_set_applicability \
      "not_applicable" \
      "" \
      "$aggregated_missing_inputs" \
      '["provide-section-times-or-use-supported-section-packages"]'
    return 0
  fi

  if [[ "$has_fallback" == "true" ]]; then
    bk_estimation_set_applicability \
      "partially_applicable" \
      "" \
      "$aggregated_missing_inputs"
    return 0
  fi

  bk_estimation_set_applicability "applicable"
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

bk_estimation_package_run() {
  local current_system="${BK_ESTIMATION_CURRENT_SYSTEM:-$est_system}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-$est_system}"
  local current_target_nodes="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
  local future_target_nodes="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"
  local model_name="${BK_ESTIMATION_MODEL_NAME:-weakscaling}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"
  local applicability_issues_json

  est_current_system="$current_system"
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="$model_name"
  est_current_bench_system="$est_system"
  est_current_bench_fom="$est_fom"
  est_current_bench_nodes="$est_node_count"
  est_current_bench_numproc_node="$est_numproc_node"
  est_current_bench_timestamp="$est_timestamp"
  est_current_bench_uuid="$est_uuid"
  est_current_fom_breakdown=$(_bk_weakscaling_transform_breakdown "$est_input_fom_breakdown" "$current_target_nodes" "$est_node_count")
  est_current_fom=$(_bk_weakscaling_breakdown_total_time "$est_current_fom_breakdown")

  est_future_system="$future_system"
  est_future_target_nodes="$future_target_nodes"
  est_future_scaling_method="$model_name"
  est_future_bench_system="$est_system"
  est_future_bench_fom="$est_fom"
  est_future_bench_nodes="$est_node_count"
  est_future_bench_numproc_node="$est_numproc_node"
  est_future_bench_timestamp="$est_timestamp"
  est_future_bench_uuid="$est_uuid"
  est_future_fom_breakdown=$(_bk_weakscaling_transform_breakdown "$est_input_fom_breakdown" "$future_target_nodes" "$est_node_count")
  est_future_fom=$(_bk_weakscaling_breakdown_total_time "$est_future_fom_breakdown")

  applicability_issues_json=$(jq -cn \
    --argjson current "$(_bk_weakscaling_collect_breakdown_package_issues "$est_current_fom_breakdown")" \
    --argjson future "$(_bk_weakscaling_collect_breakdown_package_issues "$est_future_fom_breakdown")" \
    '$current + $future')
  _bk_weakscaling_set_top_level_applicability "$applicability_issues_json"

  est_measurement_json=$(jq -cn '
    {
      tool: "application-section-timer",
      method: "section-timing",
      annotation_method: "app-defined-sections",
      counter_set: null,
      interval_timing_method: "measured"
    }')

  est_assumptions_json=$(jq -cn \
    --arg future_system "$future_system" \
    --arg current_system "$current_system" \
    --arg current_target_nodes "$current_target_nodes" \
    --arg future_target_nodes "$future_target_nodes" \
    '{
      scaling_assumption: "weak-scaling",
      baseline_system: $current_system,
      future_system_assumption: $future_system,
      current_target_nodes: $current_target_nodes,
      future_target_nodes: $future_target_nodes,
      default_section_rule: "sections and overlaps are kept identical unless a bound package applies an explicit correction",
      logp_section_rule: "sections bound to package logp are scaled with logP"
    }')

  est_model_json=$(jq -cn \
    --arg type "section-wise" \
    --arg name "$model_name" \
    --arg version "$model_version" \
    --arg implementation "scripts/estimation/packages/weakscaling.sh" \
    '{
      type: $type,
      name: $name,
      version: $version,
      implementation: $implementation
    }')
  est_current_model_json=$(jq -cn \
    --arg type "intra_system_scaling_model" \
    --arg name "weakscaling-current" \
    --arg version "$model_version" \
    --arg source_system "$est_system" \
    --arg target_system "$current_system" \
    '{
      type: $type,
      name: $name,
      version: $version,
      source_system: $source_system,
      target_system: $target_system,
      system_compatibility_rule: "same_system_line"
    }')
  est_future_model_json=$(jq -cn \
    --arg type "intra_system_scaling_model" \
    --arg name "weakscaling-future" \
    --arg version "$model_version" \
    --arg source_system "$est_system" \
    --arg target_system "$future_system" \
    '{
      type: $type,
      name: $name,
      version: $version,
      source_system: $source_system,
      target_system: $target_system,
      system_compatibility_rule: "same_system_line"
    }')

  est_confidence_json='{"level":"experimental","score":0.30}'
  est_notes_json=$(jq -cn \
    --arg note "Reference implementation for section-wise weak-scaling estimation in BenchKit." \
    '{summary: $note}')
}

bk_estimation_package_apply_metadata() {
  local package_version
  package_version=$(bk_estimation_package_metadata | jq -r '.version // "0.1"')

  bk_estimation_set_package_metadata \
    "weakscaling" \
    "$package_version" \
    "lightweight" \
    "basic"
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

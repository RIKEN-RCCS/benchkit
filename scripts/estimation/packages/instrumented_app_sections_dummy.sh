#!/bin/bash
# instrumented_app_sections_dummy.sh — Reference estimation package for
# application-defined section timings.

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
  "fallback_policy": {
    "mode": "allowed",
    "target": "lightweight_fom_scaling"
  }
}
EOF
}

_bk_section_packages_loaded=0

_bk_load_section_package_impls() {
  local package_file

  if [[ "${_bk_section_packages_loaded}" == "1" ]]; then
    return 0
  fi

  for package_file in scripts/estimation/section_packages/*.sh; do
    [[ -f "$package_file" ]] || continue
    # shellcheck disable=SC1090
    source "$package_file"
  done

  _bk_section_packages_loaded=1
}

_bk_section_package_fallback_target() {
  local package_name="$1"
  local fn_name

  _bk_load_section_package_impls

  fn_name="bk_section_package_metadata_${package_name}"
  if declare -F "$fn_name" >/dev/null 2>&1; then
    "$fn_name" | jq -r '.fallback_target // empty'
    return 0
  fi

  echo ""
}

_bk_item_has_missing_artifacts() {
  local item_json="$1"
  local path
  local artifact_count

  artifact_count=$(echo "$item_json" | jq -r '(.artifacts // []) | length')
  if [[ "$artifact_count" == "0" ]]; then
    return 0
  fi

  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if [[ ! -f "$path" ]]; then
      return 0
    fi
  done < <(echo "$item_json" | jq -r '(.artifacts // [])[]?.path')

  return 1
}

_bk_unrecoverable_bound_input_problems() {
  local breakdown_json="$1"
  local item_json
  local item_kind
  local item_name
  local package_name
  local fallback_target
  local fn_name

  _bk_load_section_package_impls

  for item_kind in section overlap; do
    while IFS= read -r item_json; do
      [[ -z "$item_json" ]] && continue
      package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
      [[ -z "$package_name" ]] && continue

      if [[ "$item_kind" == "section" ]]; then
        item_name=$(echo "$item_json" | jq -r '.name')
      else
        item_name=$(echo "$item_json" | jq -r '.sections | join(",")')
      fi

      fallback_target=$(_bk_section_package_fallback_target "$package_name")
      fn_name="bk_section_package_transform_${package_name}"

      if ! declare -F "$fn_name" >/dev/null 2>&1; then
        if [[ -z "$fallback_target" ]]; then
          printf '%s\n' "${item_kind}_package_unsupported:${item_name}:${package_name}"
        fi
        continue
      fi

      if _bk_item_has_missing_artifacts "$item_json"; then
        if [[ -z "$fallback_target" ]]; then
          if [[ "$(echo "$item_json" | jq -r '(.artifacts // []) | length')" == "0" ]]; then
            printf '%s\n' "${item_kind}_artifact:${item_name}"
          else
            while IFS= read -r path; do
              [[ -z "$path" ]] && continue
              if [[ ! -f "$path" ]]; then
                printf '%s\n' "artifact_path:${path}"
              fi
            done < <(echo "$item_json" | jq -r '(.artifacts // [])[]?.path')
          fi
        fi
      fi
    done < <(
      if [[ "$item_kind" == "section" ]]; then
        echo "$breakdown_json" | jq -c '.sections // [] | .[]'
      else
        echo "$breakdown_json" | jq -c '.overlaps // [] | .[]'
      fi
    )
  done
}

_bk_has_section_named() {
  local breakdown_json="$1"
  local section_name="$2"

  echo "$breakdown_json" | jq -e --arg section_name "$section_name" '
    (.sections // []) | any(.name == $section_name)
  ' >/dev/null 2>&1
}

_bk_missing_section_packages() {
  local breakdown_json="$1"

  echo "$breakdown_json" | jq -r '
    [
      ((.sections // [])
      | map(select((.estimation_package // "") == "") | "section_package:" + .name)),
      ((.overlaps // [])
      | map(select((.estimation_package // "") == "") | "overlap_package:" + (.sections | join(","))))
    ] | add | .[]
  '
}

_bk_missing_section_artifacts() {
  local breakdown_json="$1"

  echo "$breakdown_json" | jq -r '
    [
      ((.sections // [])
      | map(select(((.artifacts // []) | length) == 0) | "section_artifact:" + .name)),
      ((.overlaps // [])
      | map(select(((.artifacts // []) | length) == 0) | "overlap_artifact:" + (.sections | join(","))))
    ] | add | .[]
  '
}

_bk_unsupported_bound_packages() {
  local breakdown_json="$1"
  local package_name
  local fn_name

  _bk_load_section_package_impls

  while IFS= read -r package_name; do
    [[ -z "$package_name" ]] && continue
    fn_name="bk_section_package_transform_${package_name}"
    if ! declare -F "$fn_name" >/dev/null 2>&1; then
      printf '%s\n' "$package_name"
    fi
  done < <(
    echo "$breakdown_json" | jq -r '
      [
        ((.sections // [])
        | map(select((.estimation_package // "") != "") | "section_package_unsupported:" + .name + ":" + .estimation_package)),
        ((.overlaps // [])
        | map(select((.estimation_package // "") != "") | "overlap_package_unsupported:" + (.sections | join(",")) + ":" + .estimation_package))
      ] | add | .[]
    '
  )
}

bk_estimation_package_check_applicability() {
  local missing_inputs=()
  local incompatibilities=()
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local required_sections=(
    "prepare_rhs"
    "compute_hopping"
    "compute_solver"
    "halo_exchange"
    "allreduce"
    "write_result"
  )
  local section_name
  local missing_metadata

  if [[ -z "${est_fom:-}" ]]; then
    missing_inputs+=('"fom"')
  fi
  if [[ -z "${est_input_fom_breakdown:-}" || "${est_input_fom_breakdown:-}" == "null" ]]; then
    missing_inputs+=('"fom_breakdown"')
  fi

  if [[ -n "${est_input_fom_breakdown:-}" && "${est_input_fom_breakdown:-}" != "null" ]]; then
    for section_name in "${required_sections[@]}"; do
      if ! _bk_has_section_named "$est_input_fom_breakdown" "$section_name"; then
        missing_inputs+=("\"section:${section_name}\"")
      fi
    done

    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(_bk_missing_section_packages "$est_input_fom_breakdown")

    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(_bk_unsupported_bound_packages "$est_input_fom_breakdown")

    while IFS= read -r missing_metadata; do
      [[ -z "$missing_metadata" ]] && continue
      missing_inputs+=("\"${missing_metadata}\"")
    done < <(_bk_unrecoverable_bound_input_problems "$est_input_fom_breakdown")
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
    bk_estimation_set_applicability \
      "fallback" \
      "lightweight_fom_scaling" \
      "$missing_inputs_json" \
      '["use-lightweight-fom-only-estimation-or-provide-section-breakdown"]'
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

_bk_breakdown_total_time() {
  local breakdown_json="$1"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
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

_bk_scale_breakdown_to_total() {
  local breakdown_json="$1"
  local target_total="$2"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  local source_total
  source_total=$(_bk_breakdown_total_time "$breakdown_json")
  if [[ -z "$source_total" || "$source_total" == "0" ]]; then
    echo "$breakdown_json"
    return 0
  fi

  local factor
  factor=$(awk -v target="$target_total" -v source="$source_total" 'BEGIN {printf "%.12f", target / source}')
  _bk_scale_breakdown_times "$breakdown_json" "$factor"
}

_bk_attach_section_package_name() {
  local breakdown_json="$1"
  local package_name="$2"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  echo "$breakdown_json" | jq -c --arg package_name "$package_name" '
    .sections |= map(
      if (.estimation_package // "") != "" then
        .
      else
        . + {estimation_package: $package_name}
      end
    )
    | .overlaps |= map(
      if (.estimation_package // "") != "" then
        .
      else
        . + {estimation_package: $package_name}
      end
    )
  '
}

_bk_scale_breakdown_times() {
  local breakdown_json="$1"
  local factor="$2"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  echo "$breakdown_json" | jq -c --argjson factor "$factor" '
    .sections |= map(
      .
      + {time: ((.time // .bench_time // 0) * $factor)}
      + {bench_time: ((.bench_time // .time // 0) * $factor)}
      + {scaling_method: "instrumented-app-sections-dummy"}
    )
    | .overlaps |= map(
      .
      + {time: ((.time // .bench_time // 0) * $factor)}
      + {bench_time: ((.bench_time // .time // 0) * $factor)}
      + {scaling_method: "instrumented-app-sections-dummy"}
    )
  '
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

_bk_dispatch_bound_item() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  local item_kind="$5"
  local package_name
  local fn_name
  local fallback_target

  package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
  if [[ -z "$package_name" ]]; then
    echo "$item_json"
    return 0
  fi

  _bk_load_section_package_impls

  while true; do
    fn_name="bk_section_package_transform_${package_name}"
    if declare -F "$fn_name" >/dev/null 2>&1 && ! _bk_item_has_missing_artifacts "$item_json"; then
      "$fn_name" "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "$item_kind"
      return 0
    fi

    fallback_target=$(_bk_section_package_fallback_target "$package_name")
    if [[ -z "$fallback_target" || "$fallback_target" == "$package_name" ]]; then
      echo "$item_json" | jq -c '. + {scaling_method: "unresolved-package"}'
      return 0
    fi

    item_json=$(echo "$item_json" | jq -c --arg requested "$package_name" --arg applied "$fallback_target" '
      .
      + {requested_estimation_package: (.requested_estimation_package // $requested)}
      + {estimation_package: $applied}
      + {fallback_used: $applied}
    ')
    package_name="$fallback_target"
  done
}

_bk_transform_breakdown_for_qws_demo() {
  local breakdown_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  local sections_out=()
  local overlaps_out=()
  local item_json

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    sections_out+=("$(_bk_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "section")")
  done < <(echo "$breakdown_json" | jq -c '.sections // [] | .[]')

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    overlaps_out+=("$(_bk_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "overlap")")
  done < <(echo "$breakdown_json" | jq -c '.overlaps // [] | .[]')

  jq -cn \
    --argjson sections "$(printf '%s\n' "${sections_out[@]}" | jq -s '.')" \
    --argjson overlaps "$(printf '%s\n' "${overlaps_out[@]}" | jq -s '.')" \
    '{sections: $sections, overlaps: $overlaps}'
}

bk_estimation_package_run() {
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local baseline_exp="${BK_ESTIMATION_BASELINE_EXP:-CASE0}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local current_target_nodes="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
  local future_target_nodes="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"
  local model_name="${BK_ESTIMATION_MODEL_NAME:-instrumented-app-sections-dummy}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"
  local default_section_factor="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-0.5}"
  local logp_section_name="${BK_ESTIMATION_LOGP_SECTION_NAME:-allreduce}"
  local logp_package_name="trace_collective_logp"
  local breakdown_template
  local baseline_breakdown

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
    breakdown_template=$(_bk_scale_breakdown_to_total "$baseline_breakdown" "$est_current_fom")
    est_current_fom_breakdown=$(_bk_transform_breakdown_for_qws_demo \
      "$breakdown_template" \
      "$current_target_nodes" \
      "${est_current_bench_nodes:-1}" \
      "$default_section_factor")
    est_current_fom_breakdown=$(_bk_attach_section_package_name "$est_current_fom_breakdown" "instrumented_app_sections_dummy")
    est_current_fom=$(_bk_breakdown_total_time "$est_current_fom_breakdown")
  fi
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="$model_name"

  est_future_system="$future_system"
  est_future_fom_breakdown=$(_bk_transform_breakdown_for_qws_demo \
    "$est_input_fom_breakdown" \
    "$future_target_nodes" \
    "$est_node_count" \
    "$default_section_factor")
  est_future_fom_breakdown=$(_bk_attach_section_package_name "$est_future_fom_breakdown" "instrumented_app_sections_dummy")
  est_future_fom=$(_bk_breakdown_total_time "$est_future_fom_breakdown")
  est_future_target_nodes="$future_target_nodes"
  est_future_scaling_method="$model_name"

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
    --arg baseline_system "$baseline_system" \
    --arg current_target_nodes "$current_target_nodes" \
    --arg future_target_nodes "$future_target_nodes" \
    --arg default_section_factor "$default_section_factor" \
    --arg logp_section_name "$logp_section_name" \
    --arg logp_package_name "$logp_package_name" \
    '{
      scaling_assumption: "weak-scaling",
      future_system_assumption: $future_system,
      baseline_system: $baseline_system,
      current_target_nodes: $current_target_nodes,
      future_target_nodes: $future_target_nodes,
      default_section_rule: ("sections except package " + $logp_package_name + " are scaled by " + $default_section_factor),
      logp_section_rule: ("sections bound to package " + $logp_package_name + " are scaled with logP"),
      logp_reference_section: $logp_section_name,
      overlap_rule: "overlap timings are scaled by the default section factor"
    }')

  est_model_json=$(jq -cn \
    --arg type "section-wise" \
    --arg name "$model_name" \
    --arg version "$model_version" \
    --arg implementation "scripts/estimation/packages/instrumented_app_sections_dummy.sh" \
    '{
      type: $type,
      name: $name,
      version: $version,
      implementation: $implementation
    }')
  est_current_model_json=$(jq -cn \
    --arg type "intra_system_scaling_model" \
    --arg name "qws-intra-system-section-scaling" \
    --arg version "$model_version" \
    --arg source_system "$baseline_system" \
    --arg target_system "$baseline_system" \
    --arg system_compatibility_rule "exact_match" \
    '{
      type: $type,
      name: $name,
      version: $version,
      source_system: $source_system,
      target_system: $target_system,
      system_compatibility_rule: $system_compatibility_rule
    }')
  est_future_model_json=$(jq -cn \
    --arg type "cross_system_projection_model" \
    --arg name "qws-cross-system-section-projection" \
    --arg version "$model_version" \
    --arg source_system "$est_system" \
    --arg target_system "$future_system" \
    --arg system_compatibility_rule "cross_system_allowed" \
    '{
      type: $type,
      name: $name,
      version: $version,
      source_system: $source_system,
      target_system: $target_system,
      system_compatibility_rule: $system_compatibility_rule
    }')

  est_confidence_json='{"level":"experimental","score":0.20}'
  est_notes_json=$(jq -cn \
    --arg note "Reference implementation for qws-style application-defined section timings in BenchKit." \
    '{summary: $note}')
}

bk_estimation_package_apply_metadata() {
  bk_estimation_set_package_metadata \
    "instrumented_app_sections_dummy" \
    "0.1" \
    "detailed" \
    "intermediate"

  est_estimation_id="estimate-${est_code}-${est_uuid:-unknown}"
  est_estimation_timestamp=$(date '+%Y-%m-%d %H:%M:%S')
}

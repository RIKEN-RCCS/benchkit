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

bk_estimation_package_check_applicability() {
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
    bk_estimation_set_applicability \
      "fallback" \
      "lightweight_fom_scaling" \
      "$missing_inputs_json" \
      '["use-lightweight-fom-only-estimation-or-provide-section-breakdown"]'
    return 1
  fi

  bk_estimation_set_applicability "applicable"
  return 0
}

_bk_attach_section_package_name() {
  local breakdown_json="$1"
  local package_name="$2"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  echo "$breakdown_json" | jq -c --arg package_name "$package_name" '
    .sections |= map(. + {estimation_package: $package_name})
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

bk_estimation_package_run() {
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local baseline_exp="${BK_ESTIMATION_BASELINE_EXP:-CASE0}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local current_target_nodes="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
  local future_target_nodes="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"
  local future_fom_factor="${BK_ESTIMATION_FUTURE_FOM_FACTOR:-1}"
  local model_name="${BK_ESTIMATION_MODEL_NAME:-instrumented-app-sections-dummy}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"

  est_future_bench_system="$est_system"
  est_future_bench_fom="$est_fom"
  est_future_bench_nodes="$est_node_count"
  est_future_bench_numproc_node="$est_numproc_node"
  est_future_bench_timestamp="$est_timestamp"
  est_future_bench_uuid="$est_uuid"

  est_current_system="$baseline_system"
  fetch_current_fom "$baseline_system" "$est_code" "$baseline_exp"
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="measured"

  est_future_system="$future_system"
  est_future_fom=$(awk -v fom="$est_fom" -v factor="$future_fom_factor" 'BEGIN {printf "%.3f", fom * factor}')
  est_future_target_nodes="$future_target_nodes"
  est_future_scaling_method="$model_name"

  est_current_fom_breakdown=$(_bk_attach_section_package_name "$est_current_fom_breakdown" "instrumented_app_sections_dummy")
  est_future_fom_breakdown=$(_bk_scale_breakdown_times "$est_input_fom_breakdown" "${future_fom_factor}")
  est_future_fom_breakdown=$(_bk_attach_section_package_name "$est_future_fom_breakdown" "instrumented_app_sections_dummy")

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
    --arg future_fom_factor "$future_fom_factor" \
    '{
      scaling_assumption: "weak-scaling",
      future_system_assumption: $future_system,
      baseline_system: $baseline_system,
      current_target_nodes: $current_target_nodes,
      future_target_nodes: $future_target_nodes,
      section_model_rule: (
        if $future_fom_factor == "1" then
          "carry measured section and overlap timings through unchanged as a dummy reference implementation"
        else
          ($future_fom_factor + "x uniform scaling is applied to section and overlap timings as a dummy reference implementation")
        end
      )
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

  est_confidence_json='{"level":"experimental","score":0.20}'
  est_notes_json=$(jq -cn \
    --arg note "Reference implementation for application-defined section timings in BenchKit." \
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

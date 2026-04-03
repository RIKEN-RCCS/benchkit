#!/bin/bash
# lightweight_fom_scaling.sh — Reference estimation package for lightweight FOM scaling

bk_estimation_package_metadata() {
  cat <<'EOF'
{
  "name": "lightweight_fom_scaling",
  "version": "0.1",
  "method_class": "lightweight",
  "detail_level": "basic",
  "required_inputs": {
    "mandatory": ["result_json", "fom", "node_count"],
    "optional": ["fom_breakdown"],
    "external": []
  },
  "fallback_policy": {
    "mode": "none",
    "target": null
  }
}
EOF
}

bk_estimation_package_check_applicability() {
  local missing_inputs=()

  if [[ -z "${est_fom:-}" ]]; then
    missing_inputs+=('"fom"')
  fi
  if [[ -z "${est_node_count:-}" ]]; then
    missing_inputs+=('"node_count"')
  fi

  if (( ${#missing_inputs[@]} > 0 )); then
    local missing_inputs_json
    missing_inputs_json="[$(IFS=,; echo "${missing_inputs[*]}")]"
    bk_estimation_set_applicability "needs_remeasurement" "" "$missing_inputs_json" '["provide-required-estimation-inputs"]'
    return 1
  fi

  bk_estimation_set_applicability "applicable"
  return 0
}

bk_estimation_package_run() {
  local baseline_system="${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  local baseline_exp="${BK_ESTIMATION_BASELINE_EXP:-CASE0}"
  local future_system="${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  local scale_factor="${BK_ESTIMATION_SCALE_FACTOR:-2}"
  local model_name="${BK_ESTIMATION_MODEL_NAME:-scale-mock}"
  local model_version="${BK_ESTIMATION_MODEL_VERSION:-0.1}"

  # Input result is treated as the benchmark basis for the future-system side.
  est_future_bench_system="$est_system"
  est_future_bench_fom="$est_fom"
  est_future_bench_nodes="$est_node_count"
  est_future_bench_numproc_node="$est_numproc_node"
  est_future_bench_timestamp="$est_timestamp"
  est_future_bench_uuid="$est_uuid"

  # Current/baseline side.
  est_current_system="$baseline_system"
  fetch_current_fom "$est_code" "$baseline_exp"
  est_current_target_nodes="$est_node_count"
  est_current_scaling_method="measured"

  # Future/predicted side.
  est_future_system="$future_system"
  est_future_fom=$(awk -v fom="$est_fom" -v factor="$scale_factor" 'BEGIN {printf "%.3f", fom * factor}')
  est_future_target_nodes="$est_node_count"
  est_future_scaling_method="$model_name"

  est_measurement_json=$(jq -cn \
    --arg tool "benchmark-result-only" \
    --arg method "fom-plus-breakdown" \
    --arg annotation_method "none" \
    --arg counter_set "" \
    --arg interval_timing_method "measured-or-inherited" \
    '{
      tool: $tool,
      method: $method,
      annotation_method: $annotation_method,
      counter_set: ($counter_set | if . == "" then null else . end),
      interval_timing_method: $interval_timing_method
    }')

  est_assumptions_json=$(jq -cn \
    --arg future_system "$future_system" \
    --arg baseline_system "$baseline_system" \
    --arg scale_factor "$scale_factor" \
    '{
      future_system_assumption: $future_system,
      baseline_system: $baseline_system,
      future_fom_rule: ($scale_factor + "x benchmark FOM when no detailed model is available")
    }')

  est_model_json=$(jq -cn \
    --arg type "scaling" \
    --arg name "$model_name" \
    --arg version "$model_version" \
    --arg implementation "scripts/estimation/packages/lightweight_fom_scaling.sh" \
    '{
      type: $type,
      name: $name,
      version: $version,
      implementation: $implementation
    }')

  est_confidence_json='{"level":"experimental","score":0.30}'
  est_notes_json=$(jq -cn \
    --arg note "Reference implementation for lightweight estimation in BenchKit." \
    '{summary: $note}')

  local raw_breakdown=""
  if [[ -n "${BK_ESTIMATION_INPUT_JSON:-}" && -f "${BK_ESTIMATION_INPUT_JSON}" ]]; then
    raw_breakdown=$(jq -c '.fom_breakdown // empty' "${BK_ESTIMATION_INPUT_JSON}")
  fi

  if [[ -n "$raw_breakdown" ]]; then
    est_future_fom_breakdown=$(echo "$raw_breakdown" | jq -c --arg scale_factor "$scale_factor" --arg model_name "$model_name" '{
      sections: [.sections[] | {name, bench_time: .time, scaling_method: $model_name, time: (.time * ($scale_factor | tonumber))}],
      overlaps: [(.overlaps // [])[] | {sections, bench_time: .time, scaling_method: $model_name, time: (.time * ($scale_factor | tonumber))}]
    }')

    est_current_fom_breakdown=$(echo "$raw_breakdown" | jq -c '{
      sections: [.sections[] | {name, bench_time: .time, scaling_method: "measured", time: .time}],
      overlaps: [(.overlaps // [])[] | {sections, bench_time: .time, scaling_method: "measured", time: .time}]
    }')

    est_future_fom=$(echo "$est_future_fom_breakdown" | jq '([.sections[].time] | add) - ([(.overlaps // [])[].time] | add // 0)' | awk '{printf "%.3f", $1}')
    est_current_fom=$(echo "$est_current_fom_breakdown" | jq '([.sections[].time] | add) - ([(.overlaps // [])[].time] | add // 0)' | awk '{printf "%.3f", $1}')
  else
    est_future_fom_breakdown=""
    est_current_fom_breakdown=""
  fi
}

bk_estimation_package_apply_metadata() {
  bk_estimation_set_package_metadata \
    "lightweight_fom_scaling" \
    "${BK_ESTIMATION_MODEL_VERSION:-0.1}" \
    "lightweight" \
    "basic"

  est_estimation_id="estimate-${est_code}-${est_uuid:-unknown}"
  est_estimation_timestamp=$(date '+%Y-%m-%d %H:%M:%S')
}

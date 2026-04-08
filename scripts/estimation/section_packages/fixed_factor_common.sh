#!/bin/bash

bk_fixed_factor_section_package_metadata() {
  local package_name="$1"
  local fallback_target="$2"
  local item_kind_scope="${3:-[\"section\", \"overlap\"]}"
  local not_applicable_when="${4:-[\"both time and bench_time are missing\"]}"

  jq -cn \
    --arg name "$package_name" \
    --arg fallback_target "$fallback_target" \
    --argjson item_kind_scope "$item_kind_scope" \
    --argjson not_applicable_when "$not_applicable_when" \
    '{
      name: $name,
      fallback_target: (if $fallback_target == "" or $fallback_target == "null" then null else $fallback_target end),
      source_system_scope: {
        kind: "benchmark_system",
        accepted_values: ["any"]
      },
      target_system_scope: {
        accepted_values: ["any"]
      },
      item_kind_scope: $item_kind_scope,
      required_result_fields: ["time or bench_time"],
      required_artifact_kinds: [],
      acquisition_mode: "standard",
      output_fields: ["time", "bench_time", "scaling_method"],
      not_applicable_when: $not_applicable_when
    }'
}

bk_fixed_factor_section_package_check_applicability() {
  local item_json="$1"
  local required_item_kind="${2:-}"
  local actual_item_kind="${3:-}"

  if [[ -n "$required_item_kind" && "$actual_item_kind" != "$required_item_kind" ]]; then
    jq -cn --arg required "$required_item_kind" '{"status":"not_applicable","missing_inputs":["item_kind:" + $required + "_required"]}'
    return 1
  fi

  if ! echo "$item_json" | jq -e '(.time != null) or (.bench_time != null)' >/dev/null 2>&1; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_time"]}
EOF
    return 1
  fi

  cat <<'EOF'
{"status":"applicable","missing_inputs":[]}
EOF
}

bk_fixed_factor_section_package_transform() {
  local item_json="$1"
  local factor="$2"
  local scaling_method="$3"

  echo "$item_json" | jq -c --argjson factor "$factor" --arg scaling_method "$scaling_method" '
    .
    + {time: ((.time // .bench_time // 0) * $factor)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: $scaling_method}
  '
}

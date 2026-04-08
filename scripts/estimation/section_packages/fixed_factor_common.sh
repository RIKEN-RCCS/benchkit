#!/bin/bash

bk_fixed_factor_section_package_metadata() {
  local package_name="$1"
  local fallback_target="$2"

  jq -cn \
    --arg name "$package_name" \
    --arg fallback_target "$fallback_target" \
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
      item_kind_scope: ["section", "overlap"],
      required_result_fields: ["time or bench_time"],
      required_artifact_kinds: [],
      acquisition_mode: "standard",
      output_fields: ["time", "bench_time", "scaling_method"],
      not_applicable_when: ["both time and bench_time are missing"]
    }'
}

bk_fixed_factor_section_package_check_applicability() {
  local item_json="$1"

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

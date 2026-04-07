#!/bin/bash

bk_section_package_metadata_logp() {
  cat <<'EOF'
{
  "name": "logp",
  "fallback_target": "identity",
  "source_system_scope": {
    "kind": "benchmark_system",
    "accepted_values": ["any"]
  },
  "target_system_scope": {
    "accepted_values": ["any"]
  },
  "item_kind_scope": ["section"],
  "required_result_fields": ["time or bench_time"],
  "required_artifact_kinds": [],
  "output_fields": ["time", "bench_time", "scaling_method"],
  "not_applicable_when": [
    "item kind is not section",
    "both time and bench_time are missing"
  ]
}
EOF
}

bk_section_package_check_applicability_logp() {
  local item_json="$1"
  local item_kind="$2"

  if [[ "$item_kind" != "section" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:section_required"]}
EOF
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

bk_section_package_transform_logp() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  local logp_factor

  logp_factor=$(awk -v target="$target_nodes" -v bench="$bench_nodes" '
    function safe_nodes(x) { return (x < 2 ? 2 : x) }
    function lg2(x) { return log(x) / log(2) }
    BEGIN {
      printf "%.12f", lg2(safe_nodes(target)) / lg2(safe_nodes(bench))
    }')

  echo "$item_json" | jq -c --argjson factor "$logp_factor" '
    .
    + {time: ((.time // .bench_time // 0) * $factor)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: "logP"}
  '
}

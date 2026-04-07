#!/bin/bash

bk_section_package_metadata_identity() {
  cat <<'EOF'
{
  "name": "identity",
  "fallback_target": null,
  "source_system_scope": {
    "kind": "benchmark_system",
    "accepted_values": ["any"]
  },
  "target_system_scope": {
    "accepted_values": ["any"]
  },
  "item_kind_scope": ["section", "overlap"],
  "required_result_fields": ["time or bench_time"],
  "required_artifact_kinds": [],
  "acquisition_mode": "standard",
  "output_fields": ["time", "bench_time", "scaling_method"],
  "not_applicable_when": ["both time and bench_time are missing"]
}
EOF
}

bk_section_package_check_applicability_identity() {
  local item_json="$1"
  local _item_kind="$2"

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

bk_section_package_transform_identity() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"

  echo "$item_json" | jq -c '
    .
    + {time: (.time // .bench_time // 0)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: "identity"}
  '
}

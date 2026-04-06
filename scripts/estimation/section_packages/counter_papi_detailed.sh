#!/bin/bash

bk_section_package_metadata_counter_papi_detailed() {
  cat <<'EOF'
{"name":"counter_papi_detailed","fallback_target":"interval_time_simple"}
EOF
}

bk_section_package_transform_counter_papi_detailed() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local default_factor="$4"
  local _item_kind="$5"

  echo "$item_json" | jq -c --argjson factor "$default_factor" '
    .
    + {time: ((.time // .bench_time // 0) * $factor)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: "fixed-factor"}
  '
}

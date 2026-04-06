#!/bin/bash

bk_section_package_metadata_trace_mpi_basic() {
  cat <<'EOF'
{"name":"trace_mpi_basic","fallback_target":"interval_time_simple"}
EOF
}

bk_section_package_transform_trace_mpi_basic() {
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

#!/bin/bash

bk_section_package_metadata_interval_time_simple() {
  cat <<'EOF'
{"name":"interval_time_simple","fallback_target":null}
EOF
}

bk_section_package_check_applicability_interval_time_simple() {
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

bk_section_package_transform_interval_time_simple() {
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

#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/fixed_factor_common.sh"

bk_section_package_metadata_logp() {
  bk_fixed_factor_section_package_metadata \
    "logp" \
    "identity" \
    '["section"]' \
    '["item kind is not section", "both time and bench_time are missing"]'
}

bk_section_package_check_applicability_logp() {
  local item_json="$1"
  local item_kind="$2"
  bk_fixed_factor_section_package_check_applicability "$item_json" "section" "$item_kind"
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

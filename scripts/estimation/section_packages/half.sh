#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/fixed_factor_common.sh"

bk_section_package_metadata_half() {
  bk_fixed_factor_section_package_metadata "half" "identity"
}

bk_section_package_check_applicability_half() {
  local item_json="$1"
  local _item_kind="$2"
  bk_fixed_factor_section_package_check_applicability "$item_json"
}

bk_section_package_transform_half() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  bk_fixed_factor_section_package_transform "$item_json" "0.5" "fixed-factor"
}

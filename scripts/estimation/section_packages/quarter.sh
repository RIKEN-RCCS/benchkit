#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/fixed_factor_common.sh"

bk_section_package_metadata_quarter() {
  bk_fixed_factor_section_package_metadata "quarter" "identity"
}

bk_section_package_check_applicability_quarter() {
  local item_json="$1"
  local _item_kind="$2"
  bk_fixed_factor_section_package_check_applicability "$item_json"
}

bk_section_package_transform_quarter() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  bk_fixed_factor_section_package_transform "$item_json" "0.25" "fixed-factor"
}

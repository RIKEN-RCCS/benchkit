#!/bin/bash
# Common helpers for top-level estimation packages that dispatch section packages.

_bk_top_level_section_packages_loaded=0

bk_top_level_load_section_package_impls() {
  local package_file

  if [[ "${_bk_top_level_section_packages_loaded}" == "1" ]]; then
    return 0
  fi

  for package_file in scripts/estimation/section_packages/*.sh; do
    [[ -f "$package_file" ]] || continue
    # shellcheck disable=SC1090
    source "$package_file"
  done

  _bk_top_level_section_packages_loaded=1
}

bk_top_level_section_package_fallback_target() {
  local package_name="$1"
  local fn_name

  bk_top_level_load_section_package_impls

  fn_name="bk_section_package_metadata_${package_name}"
  if declare -F "$fn_name" >/dev/null 2>&1; then
    "$fn_name" | jq -r '.fallback_target // empty'
    return 0
  fi

  echo ""
}

bk_top_level_section_package_check_result() {
  local package_name="$1"
  local item_json="$2"
  local item_kind="$3"
  local fn_name

  bk_top_level_load_section_package_impls

  fn_name="bk_section_package_check_applicability_${package_name}"
  if ! declare -F "$fn_name" >/dev/null 2>&1; then
    cat <<EOF
{"status":"not_applicable","missing_inputs":["${item_kind}_package_unsupported:${package_name}"]}
EOF
    return 1
  fi

  "$fn_name" "$item_json" "$item_kind"
}

bk_top_level_dispatch_bound_item() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  local item_kind="$5"
  local default_package="$6"
  local package_name
  local fn_name
  local fallback_target
  local check_result
  local missing_inputs_json

  package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
  if [[ -z "$package_name" ]]; then
    if [[ -n "$default_package" ]]; then
      package_name="$default_package"
      item_json=$(echo "$item_json" | jq -c --arg package_name "$package_name" '. + {estimation_package: $package_name}')
    else
      echo "$item_json"
      return 0
    fi
  fi

  bk_top_level_load_section_package_impls

  while true; do
    fn_name="bk_section_package_transform_${package_name}"
    check_result=$(bk_top_level_section_package_check_result "$package_name" "$item_json" "$item_kind")
    if declare -F "$fn_name" >/dev/null 2>&1 && [[ "$(echo "$check_result" | jq -r '.status // "not_applicable"')" == "applicable" ]]; then
      "$fn_name" "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "$item_kind"
      return 0
    fi

    fallback_target=$(bk_top_level_section_package_fallback_target "$package_name")
    if [[ -z "$fallback_target" || "$fallback_target" == "$package_name" ]]; then
      missing_inputs_json=$(echo "$check_result" | jq -c '.missing_inputs // []')
      echo "$item_json" | jq -c \
        --arg requested "$package_name" \
        --argjson missing_inputs "$missing_inputs_json" '
        .
        + {requested_estimation_package: (.requested_estimation_package // $requested)}
        + {time: null}
        + {scaling_method: "unresolved-package"}
        + {package_applicability: {status: "not_applicable", missing_inputs: $missing_inputs}}
      '
      return 0
    fi

    missing_inputs_json=$(echo "$check_result" | jq -c '.missing_inputs // []')
    item_json=$(echo "$item_json" | jq -c --arg requested "$package_name" --arg applied "$fallback_target" --argjson missing_inputs "$missing_inputs_json" '
      .
      + {requested_estimation_package: (.requested_estimation_package // $requested)}
      + {estimation_package: $applied}
      + {fallback_used: $applied}
      + {package_applicability: {status: "fallback", missing_inputs: $missing_inputs}}
    ')
    package_name="$fallback_target"
  done
}

bk_top_level_transform_breakdown() {
  local breakdown_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  local default_section_package="$5"
  local default_overlap_package="$6"
  local sections_out=()
  local overlaps_out=()
  local item_json

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    sections_out+=("$(
      bk_top_level_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "section" "$default_section_package"
    )")
  done < <(echo "$breakdown_json" | jq -c '.sections // [] | .[]')

  while IFS= read -r item_json; do
    [[ -z "$item_json" ]] && continue
    overlaps_out+=("$(
      bk_top_level_dispatch_bound_item "$item_json" "$target_nodes" "$bench_nodes" "$default_factor" "overlap" "$default_overlap_package"
    )")
  done < <(echo "$breakdown_json" | jq -c '.overlaps // [] | .[]')

  jq -cn \
    --argjson sections "$(printf '%s\n' "${sections_out[@]}" | jq -s '.')" \
    --argjson overlaps "$(printf '%s\n' "${overlaps_out[@]}" | jq -s '.')" \
    '{sections: $sections, overlaps: $overlaps}'
}

bk_top_level_collect_breakdown_package_issues() {
  local breakdown_json="$1"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo "[]"
    return 0
  fi

  echo "$breakdown_json" | jq -c '
    [
      ((.sections // [])
      | map(
          {
            item_kind: "section",
            item_name: .name,
            scaling_method: (.scaling_method // ""),
            package_status: (.package_applicability.status // ""),
            missing_inputs: (.package_applicability.missing_inputs // [])
          }
        )),
      ((.overlaps // [])
      | map(
          {
            item_kind: "overlap",
            item_name: (.sections | join(",")),
            scaling_method: (.scaling_method // ""),
            package_status: (.package_applicability.status // ""),
            missing_inputs: (.package_applicability.missing_inputs // [])
          }
        ))
    ] | add
  '
}

bk_top_level_set_applicability_from_breakdowns() {
  local issues_json="$1"
  local not_applicable_advice_json="$2"
  local has_not_applicable
  local has_fallback
  local aggregated_missing_inputs

  has_not_applicable=$(echo "$issues_json" | jq -r '
    any(
      (.scaling_method == "unresolved-package")
      or (.package_status == "not_applicable")
    )
  ')

  has_fallback=$(echo "$issues_json" | jq -r '
    any(.package_status == "fallback")
  ')

  aggregated_missing_inputs=$(echo "$issues_json" | jq -c '
    [
      .[]
      | select((.missing_inputs | length) > 0)
      | .missing_inputs[]
    ] | unique
  ')

  if [[ "$has_not_applicable" == "true" ]]; then
    bk_estimation_set_applicability \
      "not_applicable" \
      "" \
      "$aggregated_missing_inputs" \
      "$not_applicable_advice_json"
    return 0
  fi

  if [[ "$has_fallback" == "true" ]]; then
    bk_estimation_set_applicability \
      "partially_applicable" \
      "" \
      "$aggregated_missing_inputs"
    return 0
  fi

  bk_estimation_set_applicability "applicable"
}

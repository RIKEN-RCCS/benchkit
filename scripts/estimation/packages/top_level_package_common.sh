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

bk_top_level_bound_package_is_supported() {
  local package_name="$1"
  local item_kind="$2"
  local metadata_key

  if ! declare -F bk_estimation_package_metadata >/dev/null 2>&1; then
    return 0
  fi

  case "$item_kind" in
    section)
      metadata_key="supported_section_packages"
      ;;
    overlap)
      metadata_key="supported_overlap_packages"
      ;;
    *)
      return 1
      ;;
  esac

  bk_estimation_package_metadata | jq -e --arg metadata_key "$metadata_key" --arg package_name "$package_name" '
    (.[$metadata_key] // []) | index($package_name) != null
  ' >/dev/null 2>&1
}

bk_top_level_unsupported_bound_package_result() {
  local package_name="$1"
  local item_kind="$2"

  cat <<EOF
{"status":"not_applicable","missing_inputs":["${item_kind}_package_unsupported:${package_name}"]}
EOF
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
    if bk_top_level_bound_package_is_supported "$package_name" "$item_kind"; then
      check_result=$(bk_top_level_section_package_check_result "$package_name" "$item_json" "$item_kind")
    else
      check_result=$(bk_top_level_unsupported_bound_package_result "$package_name" "$item_kind")
    fi
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

bk_top_level_list_missing_bound_packages() {
  local breakdown_json="$1"

  echo "$breakdown_json" | jq -r '
    [
      ((.sections // [])
      | map(select((.estimation_package // "") == "") | "section_package:" + .name)),
      ((.overlaps // [])
      | map(select((.estimation_package // "") == "") | "overlap_package:" + (.sections | join(","))))
    ] | add | .[]
  '
}

bk_top_level_list_missing_bound_artifacts() {
  local breakdown_json="$1"

  echo "$breakdown_json" | jq -r '
    [
      ((.sections // [])
      | map(select(((.artifacts // []) | length) == 0) | "section_artifact:" + .name)),
      ((.overlaps // [])
      | map(select(((.artifacts // []) | length) == 0) | "overlap_artifact:" + (.sections | join(","))))
    ] | add | .[]
  '
}

bk_top_level_list_unsupported_bound_packages() {
  local breakdown_json="$1"
  local item_json
  local item_kind
  local item_name
  local package_name
  local fn_name
  local check_name

  bk_top_level_load_section_package_impls

  for item_kind in section overlap; do
    while IFS= read -r item_json; do
      [[ -z "$item_json" ]] && continue
      package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
      [[ -z "$package_name" ]] && continue

      if [[ "$item_kind" == "section" ]]; then
        item_name=$(echo "$item_json" | jq -r '.name')
      else
        item_name=$(echo "$item_json" | jq -r '.sections | join(",")')
      fi

      fn_name="bk_section_package_transform_${package_name}"
      check_name="bk_section_package_check_applicability_${package_name}"
      if ! bk_top_level_bound_package_is_supported "$package_name" "$item_kind" || ! declare -F "$fn_name" >/dev/null 2>&1 || ! declare -F "$check_name" >/dev/null 2>&1; then
        printf '%s\n' "${item_kind}_package_unsupported:${item_name}:${package_name}"
      fi
    done < <(
      if [[ "$item_kind" == "section" ]]; then
        echo "$breakdown_json" | jq -c '.sections // [] | .[]'
      else
        echo "$breakdown_json" | jq -c '.overlaps // [] | .[]'
      fi
    )
  done
}

bk_top_level_list_unrecoverable_bound_input_problems() {
  local breakdown_json="$1"
  local item_json
  local item_kind
  local package_name
  local fallback_target
  local check_result

  bk_top_level_load_section_package_impls

  for item_kind in section overlap; do
    while IFS= read -r item_json; do
      [[ -z "$item_json" ]] && continue
      package_name=$(echo "$item_json" | jq -r '.estimation_package // empty')
      [[ -z "$package_name" ]] && continue

      fallback_target=$(bk_top_level_section_package_fallback_target "$package_name")
      if bk_top_level_bound_package_is_supported "$package_name" "$item_kind"; then
        check_result=$(bk_top_level_section_package_check_result "$package_name" "$item_json" "$item_kind")
      else
        check_result=$(bk_top_level_unsupported_bound_package_result "$package_name" "$item_kind")
      fi
      if [[ "$(echo "$check_result" | jq -r '.status // "not_applicable"')" != "applicable" && -z "$fallback_target" ]]; then
        while IFS= read -r missing_input; do
          [[ -z "$missing_input" ]] && continue
          printf '%s\n' "$missing_input"
        done < <(echo "$check_result" | jq -r '.missing_inputs // [] | .[]')
      fi
    done < <(
      if [[ "$item_kind" == "section" ]]; then
        echo "$breakdown_json" | jq -c '.sections // [] | .[]'
      else
        echo "$breakdown_json" | jq -c '.overlaps // [] | .[]'
      fi
    )
  done
}

bk_top_level_breakdown_total_time() {
  local breakdown_json="$1"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  if echo "$breakdown_json" | jq -e '
    ((.sections // []) | any((.time // null) == null))
    or
    ((.overlaps // []) | any((.time // null) == null))
  ' >/dev/null 2>&1; then
    echo "null"
    return 0
  fi

  echo "$breakdown_json" | jq -r '
    (
      (.sections // [])
      | map(.time // .bench_time // 0)
      | add // 0
    ) - (
      (.overlaps // [])
      | map(.time // .bench_time // 0)
      | add // 0
    )
  '
}

bk_top_level_scale_breakdown_times() {
  local breakdown_json="$1"
  local factor="$2"
  local scaling_method="$3"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  echo "$breakdown_json" | jq -c --argjson factor "$factor" --arg scaling_method "$scaling_method" '
    .sections |= map(
      .
      + {time: ((.time // .bench_time // 0) * $factor)}
      + {bench_time: ((.bench_time // .time // 0) * $factor)}
      + {scaling_method: $scaling_method}
    )
    | .overlaps |= map(
      .
      + {time: ((.time // .bench_time // 0) * $factor)}
      + {bench_time: ((.bench_time // .time // 0) * $factor)}
      + {scaling_method: $scaling_method}
    )
  '
}

bk_top_level_scale_breakdown_to_total() {
  local breakdown_json="$1"
  local target_total="$2"
  local scaling_method="$3"
  local source_total
  local factor

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  source_total=$(bk_top_level_breakdown_total_time "$breakdown_json")
  if [[ -z "$source_total" || "$source_total" == "0" || "$source_total" == "null" ]]; then
    echo "$breakdown_json"
    return 0
  fi

  factor=$(awk -v target="$target_total" -v source="$source_total" 'BEGIN {printf "%.12f", target / source}')
  bk_top_level_scale_breakdown_times "$breakdown_json" "$factor" "$scaling_method"
}

bk_top_level_attach_default_package_name() {
  local breakdown_json="$1"
  local package_name="$2"

  if [[ -z "$breakdown_json" || "$breakdown_json" == "null" ]]; then
    echo ""
    return 0
  fi

  echo "$breakdown_json" | jq -c --arg package_name "$package_name" '
    .sections |= map(
      if (.estimation_package // "") != "" then
        .
      else
        . + {estimation_package: $package_name}
      end
    )
    | .overlaps |= map(
      if (.estimation_package // "") != "" then
        .
      else
        . + {estimation_package: $package_name}
      end
    )
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

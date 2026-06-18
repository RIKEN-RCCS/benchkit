#!/bin/bash
# gpu_kernel_ensemble_average.sh - Run multiple GPU kernel section packages
# and use the mean of their projected times for FOM composition.

bk_section_package_metadata_gpu_kernel_ensemble_average() {
  cat <<'EOF'
{
  "name": "gpu_kernel_ensemble_average",
  "version": "0.1",
  "method_class": "detailed",
  "detail_level": "intermediate",
  "required_inputs": {
    "mandatory": ["candidate_estimation_packages"],
    "optional": ["section_artifacts"],
    "external": []
  },
  "models": {
    "section": {
      "type": "section_package_ensemble",
      "name": "gpu-kernel-ensemble-average"
    }
  },
  "fallback_target": "identity"
}
EOF
}

_bk_gpu_kernel_ensemble_packages() {
  local item_json="$1"
  local raw="${BK_GPU_KERNEL_ENSEMBLE_PACKAGES:-${BK_GENESIS_GPU_SECTION_PACKAGES:-}}"

  if echo "$item_json" | jq -e '(.candidate_estimation_packages // []) | length > 0' >/dev/null 2>&1; then
    echo "$item_json" | jq -r '.candidate_estimation_packages[]'
    return 0
  fi

  printf '%s\n' "$raw" |
    tr ',' '\n' |
    awk '{
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      if ($0 != "" && $0 != "gpu_kernel_ensemble_average") print $0
    }'
}

bk_section_package_check_applicability_gpu_kernel_ensemble_average() {
  local item_json="$1"
  local item_kind="$2"
  local packages=()
  local package_name
  local missing=()
  local transform_fn

  if [[ "$item_kind" != "section" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:section_required"]}
EOF
    return 1
  fi

  bk_top_level_load_section_package_impls
  mapfile -t packages < <(_bk_gpu_kernel_ensemble_packages "$item_json")

  if (( ${#packages[@]} == 0 )); then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["candidate_estimation_packages"]}
EOF
    return 1
  fi

  for package_name in "${packages[@]}"; do
    transform_fn="bk_section_package_transform_${package_name}"
    if ! declare -F "$transform_fn" >/dev/null 2>&1; then
      missing+=("\"section_package:${package_name}\"")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    printf '{"status":"not_applicable","missing_inputs":[%s]}\n' "$(IFS=,; echo "${missing[*]}")"
    return 1
  fi

  cat <<'EOF'
{"status":"applicable","missing_inputs":[]}
EOF
}

bk_section_package_transform_gpu_kernel_ensemble_average() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local default_factor="$4"
  local item_kind="$5"
  local packages=()
  local candidate_items=()
  local package_name
  local candidate_json
  local transformed_item
  local candidates_json

  mapfile -t packages < <(_bk_gpu_kernel_ensemble_packages "$item_json")
  for package_name in "${packages[@]}"; do
    candidate_json=$(echo "$item_json" | jq -c --arg package_name "$package_name" '
      .
      + {estimation_package: $package_name}
      | del(.candidate_estimation_packages)
    ')
    if transformed_item=$(bk_top_level_dispatch_bound_item \
      "$candidate_json" \
      "$target_nodes" \
      "$bench_nodes" \
      "$default_factor" \
      "$item_kind" \
      ""); then
      candidate_items+=("$transformed_item")
    else
      candidate_items+=("$(echo "$candidate_json" | jq -c --arg package_name "$package_name" '
        .
        + {time: null}
        + {scaling_method: "unresolved-package"}
        + {package_applicability: {status: "not_applicable", missing_inputs: ["section_package_failed:" + $package_name]}}
      ')")
    fi
  done

  candidates_json=$(printf '%s\n' "${candidate_items[@]}" | jq -s '.')

  echo "$item_json" | jq -c --argjson candidates "$candidates_json" '
    def usable_candidates:
      $candidates
      | map(select((.time // null) != null and ((.package_applicability.status // "applicable") != "not_applicable")));
    def time_ratio:
      (.metrics.section_time_ratio_predicted_over_source // .metrics.time_ratio_predicted_over_source // null);

    (usable_candidates) as $usable
    | ($usable | length) as $usable_count
    | ($candidates | length) as $candidate_count
    | ($usable | map(time_ratio) | map(select(. != null))) as $usable_ratios
    | (if $usable_count > 0 then (($usable | map(.time) | add) / $usable_count) else null end) as $mean_time
    | (if ($usable_ratios | length) > 0 then (($usable_ratios | add) / ($usable_ratios | length)) else null end) as $mean_ratio
    | .
    + {
        estimation_package: "gpu_kernel_ensemble_average",
        requested_estimation_package: (.requested_estimation_package // "gpu_kernel_ensemble_average"),
        time: $mean_time,
        scaling_method: "gpu-kernel-ensemble-average",
        package_applicability: {
          status: (
            if $usable_count == 0 then "not_applicable"
            elif $usable_count == $candidate_count then "applicable"
            else "partially_applicable"
            end
          ),
          missing_inputs: (
            $candidates
            | map(.package_applicability.missing_inputs // [])
            | add
            | unique
          )
        },
        model: {
          type: "section_package_ensemble",
          name: "GPU kernel estimator mean",
          version: "0.1"
        },
        metrics: {
          aggregation: "mean",
          candidate_count: $candidate_count,
          applicable_candidate_count: $usable_count,
          candidate_packages: ($candidates | map(.estimation_package // "")),
          candidate_times: ($candidates | map({
            estimation_package: (.estimation_package // ""),
            time: (.time // null),
            scaling_method: (.scaling_method // ""),
            applicability_status: (.package_applicability.status // "")
          })),
          candidate_time_ratios: ($candidates | map({
            estimation_package: (.estimation_package // ""),
            time_ratio_predicted_over_source: time_ratio,
            applicability_status: (.package_applicability.status // "")
          })),
          mean_time: $mean_time,
          mean_time_ratio_predicted_over_source: $mean_ratio
        },
        candidate_estimates: $candidates
      }
    | .artifacts = (
        (.artifacts // [])
        + (($candidates | map(.artifacts // []) | add) // [])
      )
  '
}

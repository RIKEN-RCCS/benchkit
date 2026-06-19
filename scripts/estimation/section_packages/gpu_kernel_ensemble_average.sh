#!/bin/bash
# gpu_kernel_ensemble_average.sh - Run multiple GPU kernel section packages
# and use a package-mean predicted/source ratio for single-kernel sections.

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
  local raw="${BK_GPU_KERNEL_ENSEMBLE_PACKAGES:-}"

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
    def candidate_time_ratio:
      (.metrics.section_time_ratio_predicted_over_source // .metrics.time_ratio_predicted_over_source // null);
    def candidate_status:
      (.package_applicability.status // "applicable");
    def usable_candidates:
      $candidates
      | map(select(
          (.time // null) != null
          and (candidate_status != "not_applicable")
          and (candidate_status != "fallback")
          and ((.estimation_package // "") != "identity")
          and ((candidate_time_ratio // 0) > 0)
        ));
    def blocking_candidates:
      $candidates
      | map(select(
          (candidate_status == "not_applicable")
          or (candidate_status == "fallback")
          or ((.estimation_package // "") == "identity")
        ));
    def candidate_kernel_records:
      map(
        . as $candidate
        | (($candidate.metrics.matched_kernels // $candidate.metrics.kernels // [])
          | to_entries
          | map(
              . as $entry
              | ($entry.value // {}) as $kernel
              | ($kernel.source_time_ns // null) as $source_time_ns
              | ($kernel.time_ratio_predicted_over_source // null) as $time_ratio
              | select($source_time_ns != null and $time_ratio != null)
              | {
                  key: (($entry.key | tostring) + "\u001f" + ($kernel.name // ("kernel_" + ($entry.key | tostring)))),
                  ordinal: $entry.key,
                  name: ($kernel.name // ("kernel_" + ($entry.key | tostring))),
                  source_time_ns: $source_time_ns,
                  source_gpu: ($kernel.source_gpu // null),
                  target_gpu: ($kernel.target_gpu // null),
                  estimation_package: ($candidate.estimation_package // ""),
                  predicted_time_ns: ($kernel.predicted_time_ns // null),
                  time_ratio_predicted_over_source: $time_ratio,
                  source_metrics: ($kernel.source_metrics // {}),
                  predicted_metrics: ($kernel.metrics // {}),
                  metric_comparisons: ($kernel.metric_comparisons // [])
                }
            )
        )
      )
      | add // [];

    (usable_candidates) as $usable
    | ($usable | length) as $usable_count
    | (blocking_candidates | length) as $blocking_count
    | ($candidates | length) as $candidate_count
    | ($usable | map(candidate_time_ratio) | map(select(. != null and . > 0))) as $usable_ratios
    | (.bench_time // .time // null) as $app_section_time
    | (
        $candidates
        | map(
            . as $candidate
            | (candidate_time_ratio) as $ratio
            | {
                estimation_package: ($candidate.estimation_package // ""),
                scaling_method: ($candidate.scaling_method // ""),
                applicability_status: ($candidate.package_applicability.status // ""),
                source_section_time: $app_section_time,
                projected_section_time: ($candidate.time // null),
                time_ratio_predicted_over_source: $ratio,
                source_gpus: ($candidate.metrics.source_gpus // []),
                target_gpus: ($candidate.metrics.target_gpus // []),
                kernel_count: ($candidate.metrics.kernel_count // (($candidate.metrics.matched_kernels // $candidate.metrics.kernels // []) | length)),
                unique_kernel_count: (($candidate.metrics.kernel_names // (($candidate.metrics.matched_kernels // $candidate.metrics.kernels // []) | map(.name // "") | unique)) | length),
                kernel_names: ($candidate.metrics.kernel_names // (($candidate.metrics.matched_kernels // $candidate.metrics.kernels // []) | map(.name // "") | unique)),
                ncu_sample: {
                  kernel_count: ($candidate.metrics.kernel_count // (($candidate.metrics.matched_kernels // $candidate.metrics.kernels // []) | length)),
                  source_time: ($candidate.metrics.total_source_time // (if ($candidate.metrics.total_source_time_ns // null) != null then ($candidate.metrics.total_source_time_ns / 1000000000) else null end)),
                  source_time_ns: ($candidate.metrics.total_source_time_ns // null),
                  predicted_time: ($candidate.metrics.sample_predicted_time // (if ($candidate.metrics.total_predicted_time_ns // null) != null then ($candidate.metrics.total_predicted_time_ns / 1000000000) else null end)),
                  predicted_time_ns: ($candidate.metrics.total_predicted_time_ns // null)
                },
                artifacts: ($candidate.artifacts // [])
              }
          )
      ) as $package_summaries
    | ($usable | candidate_kernel_records) as $kernel_records
    | ($kernel_records | map(.name) | unique | sort) as $kernel_names
    | ($kernel_names | length) as $unique_kernel_count
    | (
        $kernel_records
        | sort_by(.key)
        | group_by(.key)
        | map(
            . as $group
            | ($group[0].source_time_ns) as $source_time_ns
            | (($group | map(.time_ratio_predicted_over_source) | add) / ($group | length)) as $mean_ratio
            | {
                ordinal: $group[0].ordinal,
                name: $group[0].name,
                source_time_ns: $source_time_ns,
                source_time: ($source_time_ns / 1000000000),
                mean_time_ratio_predicted_over_source: $mean_ratio,
                projected_time_ns: ($source_time_ns * $mean_ratio),
                projected_time: (($source_time_ns * $mean_ratio) / 1000000000),
                candidate_ratios: ($group | map({
                  estimation_package: .estimation_package,
                  time_ratio_predicted_over_source: .time_ratio_predicted_over_source,
                  predicted_time_ns: .predicted_time_ns,
                  source_time_ns: .source_time_ns,
                  source_gpu: .source_gpu,
                  target_gpu: .target_gpu
                }))
              }
          )
      ) as $kernel_means
    | (
        $kernel_records
        | sort_by(.name)
        | group_by(.name)
        | map(
            . as $kernel_group
            | {
                name: $kernel_group[0].name,
                package_summaries: (
                  $kernel_group
                  | sort_by(.estimation_package)
                  | group_by(.estimation_package)
                  | map(
                      . as $package_group
                      | ($package_group | map(.source_time_ns) | map(select(. != null))) as $source_times_ns
                      | ($package_group | map(.predicted_time_ns) | map(select(. != null))) as $predicted_times_ns
                      | ($package_group | map(.time_ratio_predicted_over_source) | map(select(. != null))) as $ratios
                      | (
                          $package_group
                          | map(.metric_comparisons // [])
                          | add // []
                          | sort_by(.name)
                          | group_by(.name)
                          | map(
                              . as $metric_group
                              | ($metric_group | map(.source_value // null) | map(select(. != null))) as $source_values
                              | ($metric_group | map(.predicted_value // null) | map(select(. != null))) as $predicted_values
                              | ($metric_group | map(.ratio_predicted_over_source // null) | map(select(. != null))) as $metric_ratios
                              | {
                                  name: $metric_group[0].name,
                                  sample_count: ($metric_group | length),
                                  source_value_mean: (if ($source_values | length) > 0 then (($source_values | add) / ($source_values | length)) else null end),
                                  predicted_value_mean: (if ($predicted_values | length) > 0 then (($predicted_values | add) / ($predicted_values | length)) else null end),
                                  ratio_predicted_over_source_mean: (if ($metric_ratios | length) > 0 then (($metric_ratios | add) / ($metric_ratios | length)) else null end),
                                  samples: $metric_group
                                }
                            )
                        ) as $metric_comparisons
                      | {
                          estimation_package: $package_group[0].estimation_package,
                          sample_count: ($package_group | length),
                          source_gpus: ($package_group | map(.source_gpu // empty) | unique | sort),
                          target_gpus: ($package_group | map(.target_gpu // empty) | unique | sort),
                          source_time_ns_total: (if ($source_times_ns | length) > 0 then ($source_times_ns | add) else null end),
                          source_time_ns_mean: (if ($source_times_ns | length) > 0 then (($source_times_ns | add) / ($source_times_ns | length)) else null end),
                          predicted_time_ns_total: (if ($predicted_times_ns | length) > 0 then ($predicted_times_ns | add) else null end),
                          predicted_time_ns_mean: (if ($predicted_times_ns | length) > 0 then (($predicted_times_ns | add) / ($predicted_times_ns | length)) else null end),
                          mean_time_ratio_predicted_over_source: (if ($ratios | length) > 0 then (($ratios | add) / ($ratios | length)) else null end),
                          metric_comparisons: $metric_comparisons
                        }
                    )
                )
              }
          )
      ) as $kernel_summaries
    | (if ($usable_ratios | length) > 0 then (($usable_ratios | add) / ($usable_ratios | length)) else null end) as $mean_ratio
    | ($blocking_count == 0 and $usable_count > 0 and $unique_kernel_count == 1 and $mean_ratio != null and $app_section_time != null) as $can_project_section
    | (if $can_project_section then ($app_section_time * $mean_ratio) else $app_section_time end) as $output_time
    | .
    + {
        estimation_package: (if $can_project_section then "gpu_kernel_ensemble_average" else "identity" end),
        requested_estimation_package: (.requested_estimation_package // "gpu_kernel_ensemble_average"),
        bench_time: $app_section_time,
        time: $output_time,
        scaling_method: (if $can_project_section then "gpu-kernel-ensemble-average" else "identity" end),
        package_applicability: {
          status: (
            if $usable_count == 0 then "not_applicable"
            elif $app_section_time == null then "not_applicable"
            elif $blocking_count > 0 then "fallback"
            elif $unique_kernel_count != 1 then "fallback"
            elif $usable_count == $candidate_count then "applicable"
            elif $usable_count > 0 then "partially_applicable"
            else "partially_applicable"
            end
          ),
          missing_inputs: (
            $candidates
            | map(.package_applicability.missing_inputs // [])
            | add
            | . + (if $app_section_time == null then ["app_gpu_section_time"] else [] end)
            | . + (if $unique_kernel_count == 0 then ["gpu_kernel_ensemble_kernel_time_ratios"] else [] end)
            | . + (if $unique_kernel_count > 1 then ["gpu_kernel_section_single_kernel_required"] else [] end)
            | . + (if $blocking_count > 0 then ["gpu_kernel_ensemble_all_candidate_packages_required"] else [] end)
            | . + (if ($blocking_count == 0 and $usable_count != $candidate_count) then ["gpu_kernel_ensemble_positive_candidate_ratio_required"] else [] end)
            | unique
          )
        },
        fallback_used: (if $can_project_section then null else "identity" end),
        model: {
          type: "section_package_ensemble",
          name: "GPU kernel estimator mean",
          version: "0.1"
        },
        metrics: {
          aggregation: "single-kernel-package-ratio-mean",
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
            time_ratio_predicted_over_source: candidate_time_ratio,
            applicability_status: (.package_applicability.status // "")
          })),
          package_summaries: $package_summaries,
          kernel_count: ($kernel_records | length),
          unique_kernel_count: $unique_kernel_count,
          kernel_names: $kernel_names,
          kernel_summaries: $kernel_summaries,
          kernel_candidate_ratios: $kernel_means,
          app_gpu_section_time: $app_section_time,
          mean_time: (if $can_project_section then $output_time else null end),
          mean_time_ratio_predicted_over_source: $mean_ratio
        },
        candidate_estimates: $candidates
      }
    | if $can_project_section then del(.fallback_used) else . end
    | .artifacts = (
        (.artifacts // [])
        + (($candidates | map(.artifacts // []) | add) // [])
      )
  '
}

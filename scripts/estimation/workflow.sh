#!/bin/bash
# Shared state is provided/consumed by common.sh.
# shellcheck disable=SC2034,SC2154
# Estimation lifecycle and serialization; scientific decisions stay with the caller.

bk_estimation_work_directory() {
  local result="$1" method="$2"
  [[ "$method" =~ ^[A-Za-z0-9_-]+$ ]] || return 2
  printf 'results/estimation_artifacts/%s/%s\n' "$method" "$(basename "$result" .json)"
}

bk_estimation_run_jobs() {
  local package="$1" jobs="$2" work="$3" job index=0
  [[ "$package" =~ ^[A-Za-z0-9_]+$ ]] || return 2
  # shellcheck disable=SC1090
  source "$BK_BENCHKIT_ROOT/scripts/estimation/section_packages/$package.sh" || return
  local callback="bk_section_package_run_job_$package"
  declare -F "$callback" >/dev/null || return 2
  jq -e 'type == "array" and length > 0 and all(.[]; type == "object")' "$jobs" >/dev/null || return
  mkdir -p "$work"
  # Remove stale component results before starting; never mix different attempts.
  while [[ -f "$work/kernel_$index.json" ]]; do rm -f "$work/kernel_$index.json"; index=$((index+1)); done
  index=0
  while IFS= read -r job; do
    "$callback" "$job" "$work/kernel_$index" > "$work/kernel_$index.json.tmp" || { rm -f "$work/kernel_$index.json.tmp"; return 1; }
    jq -e 'type == "object"' "$work/kernel_$index.json.tmp" >/dev/null || return
    mv "$work/kernel_$index.json.tmp" "$work/kernel_$index.json"
    index=$((index+1))
  done < <(jq -c '.[]' "$jobs")
}

# A method supplies its projection, measurement annotations, assumptions and input
# references. The common writer owns source links, hashes and Estimate fields.
bk_estimation_write_projection() {
  local result="$1" projection="$2" measurement="$3" output="$4"
  shift 4
  local assumptions
  assumptions=$(jq -c .assumptions <<< "$projection") || return
  if [[ "${1:-}" == --assumptions ]]; then
    [[ "$#" -ge 2 ]] || return 2
    assumptions="$2"; shift 2
  fi
  read_values "$result"
  est_current_system="$est_system"
  est_future_system="$BK_ESTIMATION_FUTURE_SYSTEM"
  est_current_target_nodes="$est_node_count"
  est_future_target_nodes="$est_node_count"
  est_current_fom="$est_fom"
  est_future_fom=$(jq -er --argjson fom "$est_fom" '$fom * .time_ratio_predicted_over_source | select(. > 0 and (isinfinite | not))' <<< "$projection") || return
  est_current_scaling_method=identity
  est_future_scaling_method=$(jq -er .method <<< "$projection") || return
  bk_define_estimation_method_version "$(jq -er .version "programs/$est_code/estimate.metadata.json")"
  bk_estimation_set_package_metadata "$(jq -er .prediction_package <<< "$projection")" \
    "$(jq -er .prediction_model.version <<< "$projection")" cross_system_projection section
  bk_estimation_set_future_package_metadata "$(jq -er .prediction_package <<< "$projection")" \
    "$(jq -er .prediction_model.version <<< "$projection")"
  local identity_version side key value input kind path digest artifacts='[]'
  identity_version=$(jq -er .version scripts/estimation/section_packages/identity.metadata.json) || return
  bk_estimation_set_current_package_metadata identity "$identity_version" identity "$identity_version"
  for side in current future; do
    for key in system fom nodes numproc_node uuid timestamp; do
      case "$key" in nodes) value="$est_node_count" ;; *) local variable="est_$key"; value="${!variable}" ;; esac
      printf -v "est_${side}_bench_$key" '%s' "$value"
    done
  done
  est_future_model_json=$(jq -c '{type:"cross_system_projection_model",name:.method,version:(.schema_version | tostring),projection:.}' <<< "$projection")
  est_measurement_json=$(jq -c --argjson fom "$est_fom" '. + {result_fom_seconds:$fom}' <<< "$measurement")
  for input in "result:$result" "$@"; do
    kind="${input%%:*}"; path="${input#*:}"
    [[ -f "$path" ]] || return 1
    digest=$(sha256sum -- "$path" | awk '{print $1}') || return
    [[ "$digest" =~ ^[a-f0-9]{64}$ ]] || return 1
    artifacts=$(jq -c --arg kind "$kind" --arg path "$path" --arg sha "$digest" '. + [{kind:$kind,path:$path,sha256:$sha}]' <<< "$artifacts")
  done
  est_input_artifacts_json="$artifacts"
  est_assumptions_json="$assumptions"
  est_notes_json=$(jq -c '{status,limitations,accuracy_verified:false}' <<< "$projection")
  bk_estimation_set_applicability applicable
  bk_estimation_write_output "$output"
}

# Lifecycle for app-defined section methods. The caller chooses missing-section
# behavior and annotations; temporary inputs and the output belong to this layer.
bk_estimation_apply_annotation() {
  local annotation
  annotation=$("$1" "$2" "${est_future_fom_breakdown:-null}") || return
  est_assumptions_json=$(jq -c --argjson annotation "$annotation" '(. // {}) + $annotation' <<< "${est_assumptions_json:-null}")
}

bk_estimation_run_sections() (
  local input="$1" index="$2" annotation="${3:-}" missing_label="${4:-}" current_basis="${5:-transformed}"
  local package_input="$input" synthetic=0
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  [[ "$index" =~ ^[0-9]+$ ]] || return 2
  if [[ -n "$missing_label" ]] && ! bk_estimation_input_has_fom_breakdown "$input"; then
    package_input=$(mktemp "${TMPDIR:-/tmp}/benchkit-total-breakdown.XXXXXX.json")
    trap 'rm -f "$package_input"' EXIT
    bk_estimation_write_total_identity_breakdown_input "$input" "$package_input"
    synthetic=1
  fi
  BK_ESTIMATION_INPUT_JSON="$package_input"
  BK_ESTIMATION_SKIP_TOP_LEVEL_CURRENT_BREAKDOWN=true bk_estimation_run_declared_future_package "$package_input"
  bk_estimation_run_recorded_current_with_weakscaling \
    "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}" "${BK_ESTIMATION_BASELINE_EXP:-}" \
    "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}" "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"
  case "$current_basis" in
    recorded) est_current_fom="${est_current_bench_fom:-$est_current_fom}" ;;
    transformed) ;;
    *) return 2 ;;
  esac
  if [[ "$synthetic" = 1 ]]; then bk_estimation_mark_gpu_section_time_missing "$missing_label"; fi
  if [[ -n "$annotation" ]]; then bk_estimation_apply_annotation "$annotation" "$input"; fi
  bk_estimation_write_output "results/estimate_${est_code}_${index}.json"
)

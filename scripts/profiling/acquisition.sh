#!/bin/bash
# Common ownership of profiler outputs; command builders only select launchers.

_bk_profile_record() {
  bash "${BK_BENCHKIT_ROOT}/scripts/profiling/workflow_timing.sh" \
    --results-dir "${BK_RUN_RESULTS_DIR:-$_BK_DEFAULT_RESULTS_DIR}" "$@"
}

_bk_profile_workspace() {
  _bk_profile_record workspace --session "$_BK_WORKFLOW_SESSION_ID" \
    --output "${_BK_EXECUTION_OUTPUT:-}" --exp "${BK_RUN_EXP:-}"
}

_bk_profile_register() {
  local section="$1" file args=()
  shift
  for file in "$@"; do args+=(--artifact "$file"); done
  _bk_profile_record register --session "$_BK_WORKFLOW_SESSION_ID" \
    --output "${_BK_EXECUTION_OUTPUT:-}" --exp "${BK_RUN_EXP:-}" \
    --section "$section" "${args[@]}"
}

_bk_profile_host_command() {
  local -n prefix_ref="$1" application_ref="$2" command_ref="$3"
  command_ref=("${prefix_ref[@]}" "${application_ref[@]}")
}

_bk_profile_host_export() {
  local -n command_ref="$2"
  shift 2
  command_ref=("$@")
}

bk_ncu_window_level_args() {
  local text arg skip=0 args=()
  text=$(bk_profiler_ncu_level_args "$1") || return 1
  read -r -a args <<< "$text"
  for arg in "${args[@]}"; do
    if [ "$skip" -eq 1 ]; then skip=0; continue; fi
    case "$arg" in
      --launch-count) skip=1 ;;
      --launch-count=*) ;;
      *) printf '%s\n' "$arg" ;;
    esac
  done
}

bk_acquire_ncu() {
  local name="" slug="" kernel="" skip=0 count=1 level=single section="" discovery='{}' plan=""
  local builder=_bk_profile_host_command exporter=_bk_profile_host_export timeout_seconds=0
  while [ "$#" -gt 0 ]; do
    [ "$1" != -- ] || { shift; break; }
    [ "$#" -ge 2 ] || return 2
    case "$1" in
      --profile-name) name="$2" ;;
      --profile-slug) slug="$2" ;;
      --kernel-regex) kernel="$2" ;;
      --launch-skip) skip="$2" ;;
      --launch-count) count="$2" ;;
      --level) level="$2" ;;
      --section) section="$2" ;;
      --discovery-json) discovery="$2" ;;
      --plan) plan="$2" ;;
      --command-builder) builder="$2" ;;
      --export-builder) exporter="$2" ;;
      --timeout) timeout_seconds="$2" ;;
      *) echo 'bk_acquire_ncu: unknown option' >&2; return 2 ;;
    esac
    shift 2
  done
  [ "$#" -gt 0 ] && [ -n "$name" ] && [ -n "$kernel" ] || return 2
  [[ "$skip" =~ ^[0-9]+$ && "$count" =~ ^[1-9][0-9]*$ && "$timeout_seconds" =~ ^[0-9]+$ ]] || return 2
  if [ -n "$plan" ]; then
    discovery=$("${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" \
      --plan "$plan" --metadata "$name" --section "$section") || return 1
  fi
  local work archive metadata stage rep report status=0 level_text
  local application=("$@") prefix=() command=() export_command=() level_args=()
  slug="${slug:-$(bk_profile_slug "$name")}"
  level_text=$(bk_ncu_window_level_args "$level") || return 1
  mapfile -t level_args <<< "$level_text"
  work=$(_bk_profile_workspace) || return 1
  archive="$work/profile.tgz"; metadata="$work/profile.metadata.json"
  stage="$work/bk_profiler_artifact"; rep="$work/raw/rep1"
  mkdir -p "$rep" "$stage/raw" "$stage/reports" || return 1
  prefix=(ncu -o "$rep/profile" --target-processes all "${level_args[@]}"
    --kernel-name-base demangled --kernel-name "$kernel" --launch-skip "$skip" --launch-count "$count")
  "$builder" prefix application command || return 1
  if [ "$timeout_seconds" -gt 0 ]; then
    command=(timeout --kill-after=60s "$timeout_seconds" "${command[@]}")
  fi
  bk_profile_execute --tool ncu --phase collect --profile "$slug" --log "$work/collect.log" -- \
    "${command[@]}" </dev/null || status=$?
  report=$(bk_profiler_find_ncu_report "$rep" || true)
  if [ -n "$report" ]; then
    "$exporter" application export_command ncu --import "$report" --page raw --csv --print-units base --print-fp || return 1
    bk_profile_execute --tool ncu --phase export --profile "$slug/raw" -- \
      "${export_command[@]}" > "$rep/profile_raw.csv" 2> "$rep/profile_raw.csv.log" || true
    "$exporter" application export_command ncu --import "$report" --page details || return 1
    bk_profile_execute --tool ncu --phase export --profile "$slug/details" -- \
      "${export_command[@]}" > "$stage/reports/ncu_import_rep1.txt" 2>&1 || true
  fi
  cp -R "$rep" "$stage/raw/rep1" || return 1
  if ! bk_bool_enabled "${BK_PROFILER_ARCHIVE_NCU_REPORT:-false}"; then
    find "$stage/raw/rep1" -maxdepth 1 -type f \( -name '*.ncu-rep' -o -name '*.nsight-cuprof' \) -delete || return 1
  fi
  bk_profiler_write_meta "$stage" ncu "$level" both rep1 "$level" \
    "--kernel-name-base demangled --kernel-name $kernel --launch-skip $skip --launch-count $count" "" || return 1
  tar -czf "$archive" -C "$work" bk_profiler_artifact || return 1
  rm -rf "$stage" "$work/raw"
  # Failed acquisitions retain local diagnostics but cannot become usable profiles.
  [ "$status" -eq 0 ] || return "$status"
  [ -n "$report" ] || { echo 'NCU report was not produced' >&2; return 1; }
  bk_write_gpu_kernel_profile_metadata "$metadata" "results/$(basename "$work")/profile.tgz" \
    "$section" "$name" "$slug" "$kernel" "$skip" "$count" "$discovery" || return 1
  _bk_profile_register "$section" "$archive" "$metadata"
}

bk_discover_ncu_plan() {
  local csv="" section="" builder=_bk_profile_host_command exporter=_bk_profile_host_export
  local options=()
  while [ "$#" -gt 0 ]; do
    [ "$1" != -- ] || { shift; break; }
    [ "$#" -ge 2 ] || return 2
    case "$1" in
      --csv) csv="$2" ;;
      --section) section="$2" ;;
      --command-builder) builder="$2" ;;
      --export-builder) exporter="$2" ;;
      --top-k|--min-total-time-pct|--min-instances|--launch-count|--warmup-fraction|--max-launch-skip|--metric-set)
        options+=("$1" "$2") ;;
      *) echo 'bk_discover_ncu_plan: unknown option' >&2; return 2 ;;
    esac
    shift 2
  done
  local application=("$@") prefix=() command=() export_command=() candidates=()
  local work report discovery plan
  work=$(_bk_profile_workspace) || return 1
  report="$work/discovery.nsys-rep"; discovery="$work/discovery.json"; plan="$work/plan.json"
  if [ -z "$csv" ]; then
    [ "${#application[@]}" -gt 0 ] || return 2
    prefix=(nsys profile --force-overwrite=true --trace=cuda --sample=none -o "$work/discovery")
    "$builder" prefix application command || return 1
    bk_profile_execute --tool nsys --phase collect --log "$work/collect.log" -- "${command[@]}" >&2 || return $?
    [ -s "$report" ] || { echo 'NSYS report was not produced' >&2; return 1; }
    "$exporter" application export_command nsys stats --force-export=true --report cuda_gpu_kern_sum,cuda_api_sum \
      --format csv --output "$work/summary" "$report" || return 1
    bk_profile_execute --tool nsys --phase export -- "${export_command[@]}" >&2 || return $?
    mapfile -t candidates < <(find "$work" -maxdepth 1 -type f \( -name 'summary' -o -name 'summary*cuda_gpu_kern_sum*.csv' \) | sort)
    [ "${#candidates[@]}" -eq 1 ] || { echo 'NSYS kernel summary is missing or ambiguous' >&2; return 1; }
    csv="${candidates[0]}"
  fi
  [ -s "$csv" ] || { echo 'NSYS kernel summary is empty' >&2; return 1; }
  cp -- "$csv" "$work/kernel-summary.csv" || return 1
  (
    cd "$work" || exit 1
    bk_generate_ncu_plan --nsys-csv kernel-summary.csv --out-discovery discovery.json \
      --out-plan plan.json "${options[@]}" >&2
  ) || return $?
  [ -s "$discovery" ] && [ -s "$plan" ] || return 1
  _bk_profile_register "$section" "$discovery" "$plan" || return 1
  printf '%s\n' "$plan"
}

bk_ncu_plan_profiles() {
  "${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" \
    --plan "$1"
}

bk_capture_profile() {
  local tool="$1" level="$2" work status=0
  local BK_RUN_RESULTS_DIR="${BK_RUN_RESULTS_DIR:-$_BK_DEFAULT_RESULTS_DIR}"
  shift 2
  [ "${1:-}" != -- ] || shift
  work=$(_bk_profile_workspace) || return 1
  # The existing profiler owns its staging names inside this private directory.
  BK_PROFILER_STAGE_DIR="$work/bk_profiler_artifact" bk_profiler "$tool" --level "$level" \
    --archive "$work/profile.tgz" --raw-dir "$work/raw" -- "$@" > "$work/collect.log" || status=$?
  [ "$status" -eq 0 ] || return "$status"
  rm -rf "$work/raw"
  _bk_profile_register '' "$work/profile.tgz"
}

_bk_emit_timing_artifact() {
  local output="$1" exp="$2" fom="$3" producer="$4" parser="$5" work file
  local _BK_EXECUTION_OUTPUT="$output"
  work=$(_bk_profile_workspace) || return 1
  file="$work/timing.json"
  if ! "$parser" "$output" "$exp" "$fom" > "$file"; then
    rm -f "$file"
    return 1
  fi
  [ -s "$file" ] || { rm -f "$file"; return 0; }
  bk_record_timing_observation --artifact "results/$(basename "$work")/timing.json" \
    --id "$(basename "$work")_timing" --artifact-file "$file" --result-exp "$exp" --producer "$producer"
}

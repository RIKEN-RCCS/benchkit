#!/bin/bash
# Common ownership of profiler outputs; command builders only select launchers.

# Automatic NCU plans use Python 3.7+ and its standard library only.
# Check the selected host interpreter before acquiring NSYS data.
bk_require_ncu_plan_python() {
  local python_bin="${PYTHON_BIN:-python3}"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo "NCU plans require Python 3.7+ (standard library only); set PYTHON_BIN to an available interpreter: $python_bin" >&2
    return 1
  fi
  if ! "$python_bin" -c '
import sys
if sys.version_info < (3, 7):
    sys.exit("Python 3.7 or newer is required")
import argparse, csv, dataclasses, json, pathlib, re, shlex, typing
for name in ("generate_ncu_plan.py", "iter_ncu_plan_profiles.py", "render_ncu_plan_commands.py", "nvtx_plan.py"):
    path = pathlib.Path(sys.argv[1]) / name
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
' "${BK_BENCHKIT_ROOT}/scripts/profiling"; then
    echo "NCU plan Python check failed: $python_bin; use Python 3.7+ with the standard library via PYTHON_BIN" >&2
    return 1
  fi
}

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
    bk_require_ncu_plan_python || return 1
    section=$("${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" \
      --plan "$plan" --section-binding "$name" --section "$section") || return 1
    discovery=$("${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" \
      --plan "$plan" --metadata "$name" --section "$section") || return 1
  fi
  local nvtx_text="" nvtx_args=()
  if [ -n "$plan" ]; then
    nvtx_text=$("${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" \
      --plan "$plan" --nvtx-args "$name") || return 1
    if [ -n "$nvtx_text" ]; then mapfile -t nvtx_args <<< "$nvtx_text"; fi
  fi
  local work archive metadata stage rep report status=0 level_text
  local application=("$@") prefix=() command=() export_command=() level_args=()
  slug="${slug:-$(bk_profile_slug "$name")}"
  level_text=$(bk_ncu_window_level_args "$level") || return 1
  mapfile -t level_args <<< "$level_text"
  # The detailed preset already enables NVTX; retain only the plan's filter.
  local level_arg
  for level_arg in "${level_args[@]}"; do
    if [ "$level_arg" = --nvtx ] && [ "${nvtx_args[0]:-}" = --nvtx ]; then
      nvtx_args=("${nvtx_args[@]:1}")
      nvtx_text=$(printf '%s\n' "${nvtx_args[@]}")
      break
    fi
  done
  work=$(_bk_profile_workspace) || return 1
  archive="$work/profile.tgz"; metadata="$work/profile.metadata.json"
  stage="$work/bk_profiler_artifact"; rep="$work/raw/rep1"
  mkdir -p "$rep" "$stage/raw" "$stage/reports" || return 1
  prefix=(ncu -o "$rep/profile" --target-processes all "${level_args[@]}"
    --kernel-name-base demangled --kernel-name "$kernel" --launch-skip "$skip" --launch-count "$count" "${nvtx_args[@]}")
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
    "--kernel-name-base demangled --kernel-name $kernel --launch-skip $skip --launch-count $count ${nvtx_text//$'\n'/ }" "" || return 1
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
  local nvtx_csv="${BK_NCU_NVTX_CSV:-}" nvtx_range="${BK_NCU_NVTX_RANGE:-}"
  local nvtx_sqlite="${BK_NCU_NVTX_SQLITE:-}"
  local options=()
  while [ "$#" -gt 0 ]; do
    [ "$1" != -- ] || { shift; break; }
    [ "$#" -ge 2 ] || return 2
    case "$1" in
      --csv) csv="$2" ;;
      --nvtx-csv) nvtx_csv="$2" ;;
      --nvtx-sqlite) nvtx_sqlite="$2" ;;
      --nvtx-range) nvtx_range="$2" ;;
      --nvtx-process-id|--nvtx-thread-id) options+=("$1" "$2") ;;
      --section) section="$2" ;;
      --command-builder) builder="$2" ;;
      --export-builder) exporter="$2" ;;
      --top-k|--min-total-time-pct|--min-instances|--launch-count|--warmup-fraction|--max-launch-skip|--metric-set)
        options+=("$1" "$2") ;;
      *) echo 'bk_discover_ncu_plan: unknown option' >&2; return 2 ;;
    esac
    shift 2
  done
  if [ -n "$nvtx_sqlite" ]; then
    [ -n "$nvtx_range" ] || { echo 'NVTX SQLite requires an explicit range' >&2; return 2; }
    [ -s "$nvtx_sqlite" ] || { echo 'NVTX SQLite is empty or missing' >&2; return 1; }
  fi
  local application=("$@") prefix=() command=() export_command=() candidates=()
  local work report discovery plan
  bk_require_ncu_plan_python || return 1
  work=$(_bk_profile_workspace) || return 1
  report="$work/discovery.nsys-rep"; discovery="$work/discovery.json"; plan="$work/plan.json"
  if [ -z "$csv" ]; then
    [ "${#application[@]}" -gt 0 ] || return 2
    # Passed by name to the application command builder.
    # shellcheck disable=SC2034
    # CUDA/NVTX discovery needs no external CPU debug symbols. Apply this
    # after the application builder/login shell; keep the caller unchanged.
    prefix=(env DEBUGINFOD_URLS= nsys profile --force-overwrite=true "--trace=cuda,nvtx" --sample=none -o "$work/discovery")
    "$builder" prefix application command || return 1
    bk_profile_execute --tool nsys --phase collect --log "$work/collect.log" -- "${command[@]}" >&2 || return $?
    [ -s "$report" ] || { echo 'NSYS report was not produced' >&2; return 1; }
    "$exporter" application export_command nsys stats --force-export=true --report cuda_gpu_kern_sum,cuda_api_sum \
      --format csv --output "$work/summary" "$report" || return 1
    bk_profile_execute --tool nsys --phase export -- "${export_command[@]}" >&2 || return $?
    mapfile -t candidates < <(find "$work" -maxdepth 1 -type f \( -name 'summary' -o -name 'summary*cuda_gpu_kern_sum*.csv' \) | sort)
    [ "${#candidates[@]}" -eq 1 ] || { echo 'NSYS kernel summary is missing or ambiguous' >&2; return 1; }
    csv="${candidates[0]}"
    if [ -z "$nvtx_csv" ]; then
      "$exporter" application export_command nsys stats --force-export=true --report nvtx_kern_sum \
        --format csv --output "$work/nvtx" "$report" || return 1
      if bk_profile_execute --tool nsys --phase export -- "${export_command[@]}" >&2; then
        mapfile -t candidates < <(find "$work" -maxdepth 1 -type f -name 'nvtx*nvtx_kern_sum*.csv' | sort)
        if [ "${#candidates[@]}" -eq 1 ] && [ -s "${candidates[0]}" ]; then
          nvtx_csv="${candidates[0]}"
        fi
      fi
      if [ -z "$nvtx_csv" ]; then
        echo 'NSYS NVTX summary unavailable; retaining the unscoped kernel plan unless a range is required.' >&2
      fi
    fi
  fi
  [ -s "$csv" ] || { echo 'NSYS kernel summary is empty' >&2; return 1; }
  cp -- "$csv" "$work/kernel-summary.csv" || return 1
  if [ -n "$nvtx_csv" ]; then
    [ -s "$nvtx_csv" ] || { echo 'NVTX summary is empty or missing' >&2; return 1; }
    cp -- "$nvtx_csv" "$work/nvtx-summary.csv" || return 1
    options+=(--nvtx-csv nvtx-summary.csv)
  fi
  if [ -n "$nvtx_sqlite" ]; then
    cp -- "$nvtx_sqlite" "$work/nvtx.sqlite" || return 1
    options+=(--nvtx-sqlite nvtx.sqlite)
  fi
  if [ -n "$nvtx_range" ]; then options+=(--nvtx-range "$nvtx_range"); fi
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
  bk_require_ncu_plan_python || return 1
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

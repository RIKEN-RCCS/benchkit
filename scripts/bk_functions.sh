#!/bin/bash
# bk_functions.sh - Common functions for standardized benchmark result output.
# Source this file from Benchkit bash run/build/estimate scripts.
#
# Bash is required for the estimation and profiler helpers below.

# shellcheck source=scripts/common/bootstrap.sh
source "${BASH_SOURCE[0]%/*}/common/bootstrap.sh"
# shellcheck source=scripts/common/source.sh
source "${BK_BENCHKIT_ROOT}/scripts/common/source.sh"
# shellcheck source=scripts/common/profile_config.sh
source "${BK_BENCHKIT_ROOT}/scripts/common/profile_config.sh"
# shellcheck source=scripts/common/observation.sh
source "${BK_BENCHKIT_ROOT}/scripts/common/observation.sh"
# shellcheck source=scripts/estimation/declaration_helpers.sh
source "${BK_BENCHKIT_ROOT}/scripts/estimation/declaration_helpers.sh"

_bk_initialize_metadata() {
  local kind="$1" info="$2" items="$3"
  bash "${BK_BENCHKIT_ROOT}/scripts/runtime_metadata.sh" \
    --session "$_BK_WORKFLOW_SESSION_ID" --kind "$kind" --info "$info" --items "$items"
}

_bk_prepare_runtime() {
  _bk_initialize_metadata input \
    "${BK_INPUT_INFO_FILE:-${_BK_DEFAULT_RESULTS_DIR}/input_info.json}" \
    "${BK_INPUT_INFO_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.input_info_items.jsonl}" || return 1
  _bk_initialize_metadata timing \
    "${BK_TIMING_OBSERVATIONS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/timing_observations.json}" \
    "${BK_TIMING_OBSERVATION_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.timing_observation_items.jsonl}"
}

# Set execution scope once, before changing directory or entering a pipeline.
bk_run_context() {
  local results_dir="${BK_RUN_RESULTS_DIR:-${PWD}/results}"
  local run_exp="${BK_RUN_EXP:-}"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --results-dir|--exp)
        [ "$#" -ge 2 ] || return 2
        case "$1" in
          --results-dir) results_dir="$2" ;;
          --exp) run_exp="$2" ;;
        esac
        shift 2
        ;;
      *) echo "bk_run_context: unknown argument" >&2; return 2 ;;
    esac
  done
  case "$results_dir" in
    /*) ;;
    *) results_dir="${PWD}/${results_dir}" ;;
  esac
  export BK_RUN_RESULTS_DIR="$results_dir" BK_RUN_EXP="$run_exp"
  # An unavailable recorder must not leave a previous run eligible for collection.
  if ! rm -f "${results_dir}/.workflow_session.json"; then
    echo "Benchkit timing: previous execution context could not be invalidated" >&2
    return 0
  fi
  bash "${BK_BENCHKIT_ROOT}/scripts/profiling/workflow_timing.sh" \
    --results-dir "$results_dir" context --session "$_BK_WORKFLOW_SESSION_ID" || \
    echo "Benchkit timing: execution context could not be recorded" >&2
  return 0
}

_bk_execute_command() {
  local stage="$1" tool="$2" profile="$3" log_file="$4"
  local elapsed_variable="$5" elapsed_value=""
  shift 5
  local token="" command_status=0
  local results_dir="${BK_RUN_RESULTS_DIR:-${_BK_DEFAULT_RESULTS_DIR}}"
  local recorder="${BK_BENCHKIT_ROOT}/scripts/profiling/workflow_timing.sh"
  local command_started="" command_finished=""
  local scope_args=()
  if [ -n "${_BK_EXECUTION_OUTPUT:-}" ]; then
    scope_args=(--output "$_BK_EXECUTION_OUTPUT")
  fi
  if [ -n "${_BK_EXECUTION_INPUTS:-}" ]; then
    scope_args+=(--inputs "$_BK_EXECUTION_INPUTS")
  fi
  token=$(bash "$recorder" --results-dir "$results_dir" \
    start --session "$_BK_WORKFLOW_SESSION_ID" --exp "${BK_RUN_EXP:-}" \
    --stage "$stage" --tool "$tool" --profile "$profile" "${scope_args[@]}") || token=""
  if [ "$stage" = benchmark ]; then _BK_EXECUTION_RECORD="$token"; fi
  if [ -n "$elapsed_variable" ] && [ -z "$token" ]; then
    echo "Benchkit timing: requested elapsed time is unavailable" >&2
    return 1
  fi
  command_started=$(_bk_clock_sample start) || command_started=""
  if [ -n "$elapsed_variable" ] && [ -z "$command_started" ]; then
    echo "Benchkit timing: requested elapsed time is unavailable" >&2
    return 1
  fi
  if [ -n "$log_file" ]; then
    {
      if [ "$stage" = benchmark ]; then _BK_EXECUTION_LAUNCHED=1; fi
      "$@" || command_status=$?
    } > "$log_file" 2>&1 || command_status=$?
  else
    "$@" || command_status=$?
  fi
  command_finished=$(_bk_clock_sample finish) || command_finished=""
  if [ -n "$token" ]; then
    if [ -n "$elapsed_variable" ]; then
      if elapsed_value=$(bash "$recorder" --results-dir "$results_dir" \
          finish "$token" "$command_status" --started "$command_started" --finished "$command_finished" --print-elapsed); then
        printf -v "$elapsed_variable" '%s' "$elapsed_value"
      else
        echo "Benchkit timing: requested elapsed time could not be recorded" >&2
        [ "$command_status" -ne 0 ] || command_status=1
      fi
    else
      bash "$recorder" --results-dir "$results_dir" \
        finish "$token" "$command_status" --started "$command_started" --finished "$command_finished" || \
        echo "Benchkit timing: stage completion could not be recorded" >&2
    fi
  fi
  return "$command_status"
}

_bk_clock_sample() {
  local boundary="${1:-start}" uptime idle utc
  # Put the elapsed samples closest to the command, outside UTC collection.
  if [ "$boundary" = start ]; then
    utc=$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%S.%NZ') || return 1
    IFS=' ' read -r uptime idle < /proc/uptime || return 1
  elif [ "$boundary" = finish ]; then
    IFS=' ' read -r uptime idle < /proc/uptime || return 1
    utc=$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%S.%NZ') || return 1
  else
    return 1
  fi
  [[ "$uptime" =~ ^[0-9]{1,11}\.[0-9]{2}$ ]] || return 1
  [[ "$utc" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z$ ]] || return 1
  printf '%s|%s\n' "$uptime" "$utc"
}

bk_run() {
  local _bk_log="" _bk_elapsed="" _bk_seconds="" _bk_state="" _bk_status=0
  local _BK_EXECUTION_OUTPUT="" _BK_EXECUTION_RECORD="" _BK_EXECUTION_LAUNCHED=0
  local _BK_EXECUTION_INPUTS="" _bk_input_dir="" _bk_input_file
  local _bk_input_files=() _bk_launcher=() _bk_parameter_input=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --input-file)
        [ "$#" -ge 2 ] && [ -n "$2" ] || return 2
        _bk_input_files+=("$2"); shift 2 ;;
      --parameter-input) _bk_parameter_input=1; shift ;;
      --launcher)
        shift
        while [ "$#" -gt 0 ] && [ "$1" != -- ]; do
          _bk_launcher+=("$1"); shift
        done
        [ "${#_bk_launcher[@]}" -gt 0 ] && [ "$#" -gt 0 ] || return 2
        shift; break ;;
      --log|--elapsed)
        [ "$#" -ge 2 ] && [ -n "$2" ] || return 2
        case "$1" in
          --log) _bk_log="$2" ;;
          --elapsed) _bk_elapsed="$2" ;;
        esac
        shift 2 ;;
      --) shift; break ;;
      *) break ;;
    esac
  done
  [ "$#" -gt 0 ] || return 2
  if [ -n "$_bk_elapsed" ]; then
    [[ "$_bk_elapsed" =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]] || return 2
    printf -v "$_bk_elapsed" '%s' '' || return 2
  fi
  if [ -n "$_bk_log" ]; then
    case "$_bk_log" in
      /*) ;;
      *) _bk_log="${PWD}/${_bk_log}" ;;
    esac
    _bk_state=$(mktemp) || return 1
    if ! bash "${BK_BENCHKIT_ROOT}/scripts/run_output.sh" \
        snapshot --state "$_bk_state" --log "$_bk_log"; then
      rm -f "$_bk_state"
      return 1
    fi
  fi
  # Explicit context remains a compatibility interface for existing callers.
  if [ -n "$_bk_log" ] && [ -z "${BK_RUN_EXP:-}" ]; then
    _BK_EXECUTION_OUTPUT="$_bk_log"
    if ! _bk_prepare_runtime; then
      rm -f "$_bk_state"
      return 1
    fi
  fi
  if [ "${#_bk_input_files[@]}" -gt 0 ] || [ "$_bk_parameter_input" -eq 1 ]; then
    if [ -z "$_BK_EXECUTION_OUTPUT" ]; then
      rm -f "$_bk_state"
      echo "bk_run: input collection requires an output log without legacy context" >&2
      return 2
    fi
    if ! _bk_input_dir=$(mktemp -d "${_BK_DEFAULT_RESULTS_DIR}/.run-input.XXXXXX"); then
      echo 'bk_run: input records unavailable; execution will continue' >&2
    else
      _BK_EXECUTION_INPUTS="${_bk_input_dir}/items.jsonl"
      for _bk_input_file in "${_bk_input_files[@]}"; do
        BK_INPUT_INFO_FILE="${_bk_input_dir}/input_info.json" \
          BK_INPUT_INFO_ITEMS_FILE="${_bk_input_dir}/items.jsonl" \
          bk_record_input --file "$_bk_input_file" || _bk_status=$?
        [ "$_bk_status" -eq 0 ] || break
      done
      if [ "$_bk_parameter_input" -eq 1 ] && [ "$_bk_status" -eq 0 ]; then
        BK_INPUT_INFO_FILE="${_bk_input_dir}/input_info.json" \
          BK_INPUT_INFO_ITEMS_FILE="${_bk_input_dir}/items.jsonl" \
          bk_record_input --dataset-id command-parameters --command "$(basename "$1")" -- "${@:2}" || _bk_status=$?
      fi
      if [ ! -f "$_BK_EXECUTION_INPUTS" ]; then
        _BK_EXECUTION_INPUTS=""
        echo 'bk_run: input records unavailable; execution will continue' >&2
      fi
    fi
  fi
  if [ "$_bk_status" -eq 0 ]; then
    _bk_execute_command benchmark none "" "$_bk_log" "${_bk_elapsed:+_bk_seconds}" "${_bk_launcher[@]}" "$@" || _bk_status=$?
  fi
  [ -z "$_bk_input_dir" ] || rm -rf "$_bk_input_dir"
  if [ -n "$_bk_log" ] && [ "$_BK_EXECUTION_LAUNCHED" -eq 1 ]; then
    if ! bash "${BK_BENCHKIT_ROOT}/scripts/run_output.sh" \
        collect --state "$_bk_state" --log "$_bk_log"; then
      [ "$_bk_status" -ne 0 ] || _bk_status=1
    fi
    if [ "$_bk_status" -ne 0 ]; then
      echo "Benchkit run: command or output collection failed (status $_bk_status)" >&2
      bk_diagnose_log "$_bk_log"
    fi
    local retained_log log_name="" results_dir="${BK_RUN_RESULTS_DIR:-${_BK_DEFAULT_RESULTS_DIR}}"
    if [[ "$_BK_EXECUTION_RECORD" =~ ^workflow_timing_([0-9a-f]{64})\.json:([0-9a-f]{32})$ ]]; then
      log_name="execution-output_${BASH_REMATCH[1]}_${BASH_REMATCH[2]}.log"
    fi
    # Keep solver output even if subsequent application-side FOM extraction fails.
    if retained_log=$(mktemp "$results_dir/.execution-output.XXXXXXXX"); then
      if ! cp -- "$_bk_log" "$retained_log" || \
        ! mv -f -- "$retained_log" "$results_dir/${log_name:-execution-output.${retained_log##*.}.log}"; then
        rm -f -- "$retained_log"
        echo 'Benchkit run: execution output log unavailable' >&2
      fi
    else
      echo 'Benchkit run: execution output log unavailable' >&2
    fi
  fi
  [ -z "$_bk_state" ] || rm -f "$_bk_state"
  [ -z "$_bk_elapsed" ] || printf -v "$_bk_elapsed" '%s' "$_bk_seconds"
  return "$_bk_status"
}

bk_profile() {
  [ "${1:-}" = --from-log ] && [ "$#" -ge 4 ] || return 2
  local _BK_EXECUTION_OUTPUT="$2"
  case "$_BK_EXECUTION_OUTPUT" in
    /*) ;;
    *) _BK_EXECUTION_OUTPUT="${PWD}/${_BK_EXECUTION_OUTPUT}" ;;
  esac
  shift 2
  [ "${1:-}" = -- ] && shift
  "$@"
}

bk_diagnose_log() {
  tail -c 16384 -- "$1" | tail -n 80 >&2 || true
}

# Execute a prepared profiler command, including MPI/container launchers.
bk_profile_execute() {
  local tool="" phase="collect" profile="" log_file=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --tool|--phase|--profile|--log)
        [ "$#" -ge 2 ] || return 2
        case "$1" in
          --tool) tool="$2" ;;
          --phase) phase="$2" ;;
          --profile) profile="$2" ;;
          --log) log_file="$2" ;;
        esac
        shift 2
        ;;
      --) shift; break ;;
      *) echo "bk_profile_execute: unknown argument" >&2; return 2 ;;
    esac
  done
  [ -n "$tool" ] && [ "$#" -gt 0 ] || return 2
  case "$phase" in
    collect|export|plan) ;;
    *) echo "bk_profile_execute: unknown phase" >&2; return 2 ;;
  esac
  _bk_execute_command "$phase" "$tool" "$profile" "$log_file" "" "$@"
}

bk_generate_ncu_plan() {
  bk_profile_execute --tool ncu --phase plan -- \
    "${PYTHON_BIN:-python3}" "${BK_BENCHKIT_ROOT}/scripts/profiling/generate_ncu_plan.py" "$@"
}

# bk_emit_result - Output a standardized FOM result line.
#
# Named arguments:
#   --fom <value>          (required, numeric)
#   --fom-unit <value>     (recommended, no spaces; e.g. s, GB/s, GFLOPS)
#   --fom-version <value>  (optional)
#   --exp <value>          (optional)
#   --nodes <value>        (optional)
#   --numproc-node <value> (optional)
#   --nthreads <value>     (optional)
#   --confidential <value> (optional)
#
# Unknown arguments are silently ignored for future extensibility.
#
# Output format (omitted optional args produce no key:value pair):
#   FOM:<value> [FOM_unit:<unit>] [FOM_version:<version>] [Exp:<experiment>]
#   [node_count:<nodes>] [numproc_node:<numproc_node>] [nthreads:<nthreads>]
#   [confidential:<value>]
#
# Exit codes:
#   0 - success
#   1 - missing or invalid --fom
bk_emit_result() {
  local _bk_result_logs=()
  local timing_parser="" timing_producer="" output_index
  _bk_fom=""
  _bk_fom_unit=""
  _bk_fom_version=""
  _bk_exp=""
  _bk_nodes=""
  _bk_numproc_node=""
  _bk_nthreads=""
  _bk_confidential=""
  _bk_fom_set=0

  while [ $# -gt 0 ]; do
    case "$1" in
      --timing-parser|--timing-producer)
        [ "$#" -ge 2 ] || return 1
        if [ "$1" = --timing-parser ]; then timing_parser="$2"; else timing_producer="$2"; fi
        shift
        ;;
      --from-log)
        shift
        [ "$#" -gt 0 ] || return 1
        _bk_result_logs+=(--output "$1")
        ;;
      --fom)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_emit_result: --fom requires a value" >&2
          return 1
        fi
        _bk_fom="$1"
        _bk_fom_set=1
        ;;
      --fom-unit)
        shift
        if [ $# -gt 0 ]; then
          _bk_fom_unit="$1"
        fi
        ;;
      --fom-version)
        shift
        if [ $# -gt 0 ]; then
          _bk_fom_version="$1"
        fi
        ;;
      --exp)
        shift
        if [ $# -gt 0 ]; then
          _bk_exp="$1"
        fi
        ;;
      --nodes)
        shift
        if [ $# -gt 0 ]; then
          _bk_nodes="$1"
        fi
        ;;
      --numproc-node)
        shift
        if [ $# -gt 0 ]; then
          _bk_numproc_node="$1"
        fi
        ;;
      --nthreads)
        shift
        if [ $# -gt 0 ]; then
          _bk_nthreads="$1"
        fi
        ;;
      --confidential)
        shift
        if [ $# -gt 0 ]; then
          _bk_confidential="$1"
        fi
        ;;
      --*)
        # Unknown named argument: skip its value if present
        shift
        if [ $# -gt 0 ]; then
          case "$1" in
            --*) continue ;;  # Next arg is another flag, don't consume it
            *) ;;             # Consume the value
          esac
        fi
        ;;
      *)
        # Ignore positional arguments
        ;;
    esac
    shift
  done

  # Validate --fom is provided
  if [ "$_bk_fom_set" -eq 0 ]; then
    echo "bk_emit_result: --fom is required" >&2
    return 1
  fi

  # Validate --fom is numeric (integer or decimal, with optional leading minus)
  case "$_bk_fom" in
    *[!0-9.eE+-]*)
      echo "bk_emit_result: --fom value must be numeric, got '$_bk_fom'" >&2
      return 1
      ;;
    "")
      echo "bk_emit_result: --fom value must be numeric, got ''" >&2
      return 1
      ;;
  esac
  # Additional check: must contain at least one digit
  case "$_bk_fom" in
    *[0-9]*)
      ;;
    *)
      echo "bk_emit_result: --fom value must be numeric, got '$_bk_fom'" >&2
      return 1
      ;;
  esac

  # Canonicalize scientific notation where awk can do so without losing precision.
  # Very small values may remain in scientific notation; result.sh accepts both.
  case "$_bk_fom" in
    *[eE]*)
      _bk_fom=$(awk "BEGIN {printf \"%.17g\", $_bk_fom}")
      ;;
  esac

  if [ "${#_bk_result_logs[@]}" -gt 0 ]; then
    bash "${BK_BENCHKIT_ROOT}/scripts/profiling/workflow_timing.sh" \
      --results-dir "${BK_RUN_RESULTS_DIR:-$_BK_DEFAULT_RESULTS_DIR}" bind \
      --session "$_BK_WORKFLOW_SESSION_ID" --exp "$_bk_exp" "${_bk_result_logs[@]}" || \
      echo "Benchkit timing: output association unavailable; FOM is retained" >&2
  fi
  if [ -n "$timing_parser" ]; then
    for ((output_index=1; output_index<${#_bk_result_logs[@]}; output_index+=2)); do
      _bk_emit_timing_artifact "${_bk_result_logs[$output_index]}" "$_bk_exp" "$_bk_fom" \
        "$timing_producer" "$timing_parser" || echo 'Benchkit timing: parser observation unavailable; FOM is retained' >&2
    done
  fi

  # Build output line
  _bk_output="FOM:${_bk_fom}"

  if [ -n "$_bk_fom_unit" ]; then
    _bk_output="${_bk_output} FOM_unit:${_bk_fom_unit}"
  fi

  if [ -n "$_bk_fom_version" ]; then
    _bk_output="${_bk_output} FOM_version:${_bk_fom_version}"
  fi

  if [ -n "$_bk_exp" ]; then
    _bk_output="${_bk_output} Exp:${_bk_exp}"
  fi

  if [ -n "$_bk_nodes" ]; then
    _bk_output="${_bk_output} node_count:${_bk_nodes}"
  fi

  if [ -n "$_bk_numproc_node" ]; then
    _bk_output="${_bk_output} numproc_node:${_bk_numproc_node}"
  fi

  if [ -n "$_bk_nthreads" ]; then
    _bk_output="${_bk_output} nthreads:${_bk_nthreads}"
  fi

  if [ -n "$_bk_confidential" ]; then
    _bk_output="${_bk_output} confidential:${_bk_confidential}"
  fi

  echo "$_bk_output"
  return 0
}





































# Nsight Compute changed report suffixes across releases, so look for all names
# we have seen instead of hard-coding only .ncu-rep.
bk_profiler_find_ncu_report() {
  _bk_ncu_report_dir="$1"
  find "$_bk_ncu_report_dir" -maxdepth 1 -type f \( \
    -name '*.ncu-rep' -o \
    -name '*.nsight-cuprof' -o \
    -name 'profile*' \
  \) \
    ! -name 'profile_raw.csv' \
    ! -name 'profile_raw.csv.log' \
    ! -name '*.csv' \
    ! -name '*.log' \
    | head -n 1
}

bk_json_escape() {
  _bk_json_value="$1"
  _bk_json_value=${_bk_json_value//\\/\\\\}
  _bk_json_value=${_bk_json_value//\"/\\\"}
  _bk_json_value=${_bk_json_value//$'\t'/\\t}
  _bk_json_value=${_bk_json_value//$'\r'/\\r}
  _bk_json_value=${_bk_json_value//$'\n'/\\n}
  printf '%s' "$_bk_json_value"
}

bk_json_string() {
  printf '"'
  bk_json_escape "$1"
  printf '"'
}

bk_json_string_array() {
  _bk_json_first=1
  printf '['
  for _bk_json_item in "$@"; do
    if [ "$_bk_json_first" -eq 0 ]; then
      printf ', '
    fi
    bk_json_string "$_bk_json_item"
    _bk_json_first=0
  done
  printf ']'
}



# bk_record_input_info - Pass benchmark input metadata to Benchkit.
#
# Usage:
#   bk_record_input_info path/to/input-info.json
#   bk_record_input_info <<'EOF'
#   {"schema_version": 1, "inputs": [...]}
#   EOF
#
# The file path used by the common result packaging layer is intentionally kept
# behind this helper so app scripts can focus on dataset identity and evidence.
bk_record_input_info() {
  if [ $# -gt 1 ]; then
    echo "bk_record_input_info: accepts at most one JSON file path" >&2
    return 1
  fi

  _bk_input_info_file="${BK_INPUT_INFO_FILE:-${_BK_DEFAULT_RESULTS_DIR}/input_info.json}"
  _bk_input_info_dir=$(dirname "$_bk_input_info_file")
  mkdir -p "$_bk_input_info_dir" || return 1
  _bk_input_info_tmp=$(mktemp "${_bk_input_info_file}.tmp.XXXXXX") || return 1

  if [ $# -eq 1 ]; then
    _bk_input_info_source="$1"
    if [ ! -f "$_bk_input_info_source" ]; then
      echo "bk_record_input_info: input info JSON file not found: $_bk_input_info_source" >&2
      rm -f "$_bk_input_info_tmp"
      return 1
    fi
    if ! cp "$_bk_input_info_source" "$_bk_input_info_tmp"; then
      rm -f "$_bk_input_info_tmp"
      return 1
    fi
  elif ! cat > "$_bk_input_info_tmp"; then
    rm -f "$_bk_input_info_tmp"
    return 1
  fi

  if [ ! -s "$_bk_input_info_tmp" ]; then
    echo "bk_record_input_info: input info JSON must not be empty" >&2
    rm -f "$_bk_input_info_tmp"
    return 1
  fi

  if command -v jq >/dev/null 2>&1; then
    if ! jq -e 'type == "object"' "$_bk_input_info_tmp" >/dev/null 2>&1; then
      echo "bk_record_input_info: input info must be a JSON object" >&2
      rm -f "$_bk_input_info_tmp"
      return 1
    fi
  fi

  if ! mv "$_bk_input_info_tmp" "$_bk_input_info_file"; then
    rm -f "$_bk_input_info_tmp"
    return 1
  fi
}

bk_reset_input_info() {
  _bk_reset_info_file="${BK_INPUT_INFO_FILE:-${_BK_DEFAULT_RESULTS_DIR}/input_info.json}"
  _bk_reset_items_file="${BK_INPUT_INFO_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.input_info_items.jsonl}"
  rm -f "$_bk_reset_info_file" "$_bk_reset_items_file"
}

_bk_record_input_info_items_file() {
  _bk_items_info_file="$1"
  _bk_items_jsonl_file="$2"

  {
    printf '{\n'
    printf '  "schema_version": 1,\n'
    printf '  "inputs": [\n'
    _bk_items_first=1
    while IFS= read -r _bk_items_item; do
      [ -n "$_bk_items_item" ] || continue
      if [ "$_bk_items_first" -eq 0 ]; then
        printf ',\n'
      fi
      printf '    %s' "$_bk_items_item"
      _bk_items_first=0
    done < "$_bk_items_jsonl_file"
    printf '\n'
    printf '  ]\n'
    printf '}\n'
  } | BK_INPUT_INFO_FILE="$_bk_items_info_file" bk_record_input_info
}

_bk_input_item_string_field() {
  _bk_field_name="$1"
  _bk_field_value="$2"
  [ -n "$_bk_field_value" ] || return 0
  if [ "$_bk_input_item_first" -eq 0 ]; then
    printf ','
  fi
  bk_json_string "$_bk_field_name"
  printf ':'
  bk_json_string "$_bk_field_value"
  _bk_input_item_first=0
}

_bk_record_input_item() {
  _bk_item_dataset_id=""
  _bk_item_dataset_version=""
  _bk_item_kind=""
  _bk_item_source=""
  _bk_item_parameter_set_id=""
  _bk_item_result_exp=""
  _bk_item_repo_relative_path=""
  _bk_item_public_url=""
  _bk_item_source_url=""
  _bk_item_source_ref=""
  _bk_item_resolved_commit=""
  _bk_item_verification_status=""
  _bk_item_sha256=""
  _bk_item_size_bytes=""
  _bk_item_collection_status=""
  _bk_item_collection_error=""
  _bk_item_observation=""
  _bk_item_recipe=""
  _bk_item_command=""
  _bk_item_arguments=()
  _bk_item_parameter_keys=()
  _bk_item_parameter_values=()
  local observation_args=() item_json

  while [ $# -gt 0 ]; do
    case "$1" in
      --dataset-id)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --dataset-id requires a value" >&2
          return 1
        fi
        shift
        _bk_item_dataset_id="$1"
        ;;
      --dataset-version)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --dataset-version requires a value" >&2
          return 1
        fi
        shift
        _bk_item_dataset_version="$1"
        ;;
      --kind)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --kind requires a value" >&2
          return 1
        fi
        shift
        _bk_item_kind="$1"
        ;;
      --source)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --source requires a value" >&2
          return 1
        fi
        shift
        _bk_item_source="$1"
        ;;
      --parameter-set-id)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --parameter-set-id requires a value" >&2
          return 1
        fi
        shift
        _bk_item_parameter_set_id="$1"
        ;;
      --result-exp)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --result-exp requires a value" >&2
          return 1
        fi
        shift
        _bk_item_result_exp="$1"
        ;;
      --repo-relative-path)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --repo-relative-path requires a value" >&2
          return 1
        fi
        shift
        _bk_item_repo_relative_path="$1"
        ;;
      --public-url)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --public-url requires a value" >&2
          return 1
        fi
        shift
        _bk_item_public_url="$1"
        ;;
      --source-url)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --source-url requires a value" >&2
          return 1
        fi
        shift
        _bk_item_source_url="$1"
        ;;
      --source-ref)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --source-ref requires a value" >&2
          return 1
        fi
        shift
        _bk_item_source_ref="$1"
        ;;
      --resolved-commit)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --resolved-commit requires a value" >&2
          return 1
        fi
        shift
        _bk_item_resolved_commit="$1"
        ;;
      --verification-status)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --verification-status requires a value" >&2
          return 1
        fi
        shift
        _bk_item_verification_status="$1"
        ;;
      --sha256|--size-bytes)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: $1 requires a value" >&2
          return 1
        fi
        case "$1" in
          --sha256) _bk_item_sha256="$2" ;;
          --size-bytes) _bk_item_size_bytes="$2" ;;
        esac
        shift
        ;;
      --collection-status|--collection-error)
        [ "$#" -ge 2 ] || return 1
        if [ "$1" = --collection-status ]; then
          _bk_item_collection_status="$2"
        else
          _bk_item_collection_error="$2"
        fi
        shift
        ;;
      --file|--directory|--expected-manifest)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: missing collection argument" >&2
          return 1
        fi
        observation_args+=("$1" "$2")
        shift
        ;;
      --recipe)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --recipe requires a value" >&2
          return 1
        fi
        shift
        _bk_item_recipe="$1"
        ;;
      --command)
        if [ $# -lt 2 ]; then
          echo "bk_record_input_item: --command requires a value" >&2
          return 1
        fi
        shift
        _bk_item_command="$1"
        ;;
      --parameter)
        if [ $# -lt 3 ]; then
          echo "bk_record_input_item: --parameter requires a key and value" >&2
          return 1
        fi
        shift
        _bk_item_parameter_keys+=("$1")
        shift
        _bk_item_parameter_values+=("$1")
        ;;
      --)
        shift
        _bk_item_arguments=("$@")
        break
        ;;
      *)
        echo "bk_record_input_item: unknown option: $1" >&2
        return 1
        ;;
    esac
    shift
  done

  if [ -z "$_bk_item_dataset_id" ]; then
    echo "bk_record_input_item: --dataset-id is required" >&2
    return 1
  fi
  if [ -z "$_bk_item_kind" ]; then
    echo "bk_record_input_item: --kind is required" >&2
    return 1
  fi
  if [ -z "$_bk_item_source" ]; then
    echo "bk_record_input_item: --source is required" >&2
    return 1
  fi
  if [ -z "$_bk_item_verification_status" ]; then
    _bk_item_verification_status="declared"
  fi
  if [ -n "$_bk_item_sha256" ]; then
    bk_validate_hex_length "$_bk_item_sha256" 64 "input sha256" || return 1
  fi
  if [ -n "$_bk_item_size_bytes" ] && ! [[ "$_bk_item_size_bytes" =~ ^(0|[1-9][0-9]*)$ ]]; then
    echo "bk_record_input_item: invalid byte count" >&2
    return 1
  fi

  _bk_item_info_file="${BK_INPUT_INFO_FILE:-${_BK_DEFAULT_RESULTS_DIR}/input_info.json}"
  _bk_item_items_file="${BK_INPUT_INFO_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.input_info_items.jsonl}"

  item_json=$(_bk_input_item_json) || return 1

  if [ "${#observation_args[@]}" -gt 0 ]; then
    local observed_json observation_status source_path metadata_path destination
    IFS= read -r -d '' source_path < <(realpath -mz -- "${observation_args[1]}") || return 1
    for destination in "$_bk_item_info_file" "$_bk_item_items_file" "${_BK_DEFAULT_RESULTS_DIR}/.input_references"; do
      IFS= read -r -d '' metadata_path < <(realpath -mz -- "$destination") || return 1
      if [[ "$metadata_path" = "$source_path" ]] || \
        { [[ "${observation_args[0]}" = --directory && "$metadata_path" = "${source_path%/}/"* ]]; }; then
        echo 'bk_record_input: metadata output must be outside the input' >&2
        return 1
      fi
    done
    if observed_json=$(bash "${BK_BENCHKIT_ROOT}/scripts/input_manifest.sh" "${observation_args[@]}" \
        --references-dir "${_BK_DEFAULT_RESULTS_DIR}/.input_references" 2>/dev/null); then
      _bk_item_observation="$observed_json"
      item_json=$(_bk_input_item_json) || return 1
    else
      observation_status=$?
      if [ "$observation_status" -eq 2 ]; then
        echo 'bk_record_input: invalid input metadata destination or collector arguments' >&2
        return 1
      fi
      _bk_item_collection_status=unavailable
      _bk_item_collection_error=collector_failed
      _bk_item_verification_status=unavailable
      _bk_item_sha256="" _bk_item_size_bytes=""
      echo 'bk_record_input: input observation unavailable; execution may continue' >&2
      item_json=$(_bk_input_item_json) || return 1
    fi
  fi
  if ! _bk_initialize_metadata input "$_bk_item_info_file" "$_bk_item_items_file" \
    || ! mkdir -p "$(dirname "$_bk_item_items_file")" \
    || ! printf '%s\n' "$item_json" >> "$_bk_item_items_file" \
    || ! _bk_record_input_info_items_file "$_bk_item_info_file" "$_bk_item_items_file"; then
    echo 'bk_record_input: input record could not be stored; execution may continue' >&2
  fi
  return 0
}

_bk_input_item_json() {
    _bk_input_item_first=1
    printf '{'
    _bk_input_item_string_field "dataset_id" "$_bk_item_dataset_id"
    _bk_input_item_string_field "dataset_version" "$_bk_item_dataset_version"
    _bk_input_item_string_field "kind" "$_bk_item_kind"
    _bk_input_item_string_field "source" "$_bk_item_source"
    _bk_input_item_string_field "parameter_set_id" "$_bk_item_parameter_set_id"
    _bk_input_item_string_field "result_exp" "$_bk_item_result_exp"
    _bk_input_item_string_field "repo_relative_path" "$_bk_item_repo_relative_path"
    _bk_input_item_string_field "public_url" "$_bk_item_public_url"
    _bk_input_item_string_field "source_url" "$_bk_item_source_url"
    _bk_input_item_string_field "source_ref" "$_bk_item_source_ref"
    _bk_input_item_string_field "resolved_commit" "$_bk_item_resolved_commit"
    _bk_input_item_string_field "verification_status" "$_bk_item_verification_status"
    _bk_input_item_string_field "collection_status" "$_bk_item_collection_status"
    _bk_input_item_string_field "collection_error" "$_bk_item_collection_error"
    _bk_input_item_string_field "sha256" "$_bk_item_sha256"
    if [ -n "$_bk_item_observation" ]; then
      printf ',"observation_capture":%s' "$_bk_item_observation"
    fi
    if [ -n "$_bk_item_size_bytes" ]; then
      printf ',"size_bytes":%s' "$_bk_item_size_bytes"
    fi
    _bk_input_item_string_field "recipe" "$_bk_item_recipe"
    if [ -n "$_bk_item_command" ]; then
      _bk_input_item_string_field "command" "$_bk_item_command"
      if [ "$_bk_input_item_first" -eq 0 ]; then
        printf ','
      fi
      printf '"arguments":'
      bk_json_string_array "${_bk_item_arguments[@]}"
      _bk_input_item_first=0
    fi
    if [ "${#_bk_item_parameter_keys[@]}" -gt 0 ]; then
      if [ "$_bk_input_item_first" -eq 0 ]; then
        printf ','
      fi
      printf '"parameters":{'
      _bk_param_first=1
      for _bk_param_index in "${!_bk_item_parameter_keys[@]}"; do
        if [ "$_bk_param_first" -eq 0 ]; then
          printf ','
        fi
        bk_json_string "${_bk_item_parameter_keys[$_bk_param_index]}"
        printf ':'
        bk_json_string "${_bk_item_parameter_values[$_bk_param_index]}"
        _bk_param_first=0
      done
      printf '}'
      _bk_input_item_first=0
    fi
    printf '}\n'
}

bk_record_input() {
  _bk_input_dataset_id=""
  _bk_input_dataset_version=""
  _bk_input_type=""
  _bk_input_repo_url=""
  _bk_input_ref=""
  _bk_input_commit=""
  _bk_input_result_exp=""
  _bk_input_path=""
  _bk_input_parameter_set_id=""
  _bk_input_command=""
  _bk_input_recipe=""
  _bk_input_verify_requested=0
  _bk_input_verify_file=""
  _bk_input_expected_sha256=""
  _bk_input_expected_size_bytes=""
  local collection_status="" collection_error=""
  local _bk_input_actual_sha256="" _bk_input_actual_size=""
  _bk_input_arguments=()
  _bk_input_parameter_args=()
  local observation_kind="" observation_args=() expected_manifest=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --dataset-id)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --dataset-id requires a value" >&2
          return 1
        fi
        shift
        _bk_input_dataset_id="$1"
        ;;
      --version|--dataset-version)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_input_dataset_version="$1"
        ;;
      --type)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --type requires a value" >&2
          return 1
        fi
        shift
        _bk_input_type="$1"
        ;;
      --verify-file|--expected-sha256|--expected-size-bytes)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        _bk_input_verify_requested=1
        case "$1" in
          --verify-file) _bk_input_verify_file="$2" ;;
          --expected-sha256) _bk_input_expected_sha256="$2" ;;
          --expected-size-bytes) _bk_input_expected_size_bytes="$2" ;;
        esac
        shift
        ;;
      --file|--directory)
        if [ $# -lt 2 ] || [ -z "$2" ] || [ -n "$observation_kind" ]; then
          echo "bk_record_input: specify one nonempty --file or --directory" >&2
          return 1
        fi
        observation_kind="${1#--}"
        observation_args+=("$1" "$2")
        shift
        ;;
      --expected-manifest)
        if [ $# -lt 2 ] || [ -z "$2" ]; then
          echo "bk_record_input: --expected-manifest requires a value" >&2
          return 1
        fi
        expected_manifest="$2"
        shift
        ;;
      --repo-url|--source-url|--public-url)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_input_repo_url="$1"
        ;;
      --ref|--source-ref)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_input_ref="$1"
        ;;
      --commit|--resolved-commit)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_input_commit="$1"
        ;;
      --result-exp)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --result-exp requires a value" >&2
          return 1
        fi
        shift
        _bk_input_result_exp="$1"
        ;;
      --path|--repo-relative-path)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_input_path="$1"
        ;;
      --parameter-set-id)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --parameter-set-id requires a value" >&2
          return 1
        fi
        shift
        _bk_input_parameter_set_id="$1"
        ;;
      --command)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --command requires a value" >&2
          return 1
        fi
        shift
        _bk_input_command="$1"
        ;;
      --recipe)
        if [ $# -lt 2 ]; then
          echo "bk_record_input: --recipe requires a value" >&2
          return 1
        fi
        shift
        _bk_input_recipe="$1"
        ;;
      --parameter)
        if [ $# -lt 3 ]; then
          echo "bk_record_input: --parameter requires a key and value" >&2
          return 1
        fi
        shift
        _bk_input_parameter_args+=(--parameter "$1")
        shift
        _bk_input_parameter_args+=("$1")
        ;;
      --)
        shift
        _bk_input_arguments=("$@")
        break
        ;;
      *)
        echo "bk_record_input: unknown option: $1" >&2
        return 1
        ;;
    esac
    shift
  done

  if [ -n "$observation_kind" ]; then
    if [ "$_bk_input_verify_requested" -eq 1 ]; then
      echo "bk_record_input: do not mix collection and single-file verification options" >&2
      return 1
    fi
    if [ -z "$_bk_input_type" ]; then
      case "$observation_kind" in
        file) _bk_input_type=file ;;
        directory) _bk_input_type=dataset ;;
      esac
    fi
    case "$observation_kind:$_bk_input_type" in
      file:file|file:matrix|file:archive|file:tar|file:tgz|directory:input|directory:dataset|directory:restart) ;;
      *) echo "bk_record_input: collection kind and input type do not match" >&2; return 1 ;;
    esac
    if [ -n "$expected_manifest" ]; then
      observation_args+=(--expected-manifest "$expected_manifest")
    fi
    if [ -z "$_bk_input_dataset_id" ]; then
      _bk_input_dataset_id="input-${observation_kind}"
    fi
  elif [ -n "$expected_manifest" ]; then
    echo "bk_record_input: --expected-manifest requires --file or --directory" >&2
    return 1
  fi

  _bk_input_has_parameters=0
  if [ "${#_bk_input_parameter_args[@]}" -gt 0 ]; then
    _bk_input_has_parameters=1
  fi

  if [ -n "$_bk_input_type" ]; then
    case "$_bk_input_type" in
      archive|tar|tgz)
        _bk_input_kind="pre-staged-archive"
        ;;
      file|matrix)
        _bk_input_kind="pre-staged-file"
        ;;
      input|dataset)
        _bk_input_kind="pre-staged-input"
        ;;
      restart)
        _bk_input_kind="pre-staged-restart"
        ;;
      *)
        echo "bk_record_input: unsupported --type: $_bk_input_type" >&2
        return 1
        ;;
    esac
  elif [ -n "$_bk_input_repo_url" ]; then
    _bk_input_kind="git-repository"
  elif [ -n "$_bk_input_path" ]; then
    _bk_input_kind="repo-local-input"
  elif [ -n "$_bk_input_command" ]; then
    _bk_input_kind="runtime-parameters"
  elif [ "$_bk_input_has_parameters" -eq 1 ]; then
    _bk_input_kind="inline-parameters"
  else
    echo "bk_record_input: cannot infer input; pass --parameter, --command, --repo-url, --type, or --path" >&2
    return 1
  fi

  if [ -n "$_bk_input_repo_url" ]; then
    _bk_input_source="source_url"
  elif [ -n "$_bk_input_path" ] && [ -z "$_bk_input_type" ]; then
    _bk_input_source="source_info"
  elif [ -n "$_bk_input_type" ]; then
    _bk_input_source="site-local"
  elif [ -n "$_bk_input_command" ] || [ "$_bk_input_has_parameters" -eq 1 ]; then
    _bk_input_source="inline"
  else
    _bk_input_source="declared"
  fi

  if [ -n "$_bk_input_repo_url" ] && [ -n "$_bk_input_commit" ]; then
    _bk_input_verification_status="source_commit"
  elif [ -n "$_bk_input_path" ] && [ -z "$_bk_input_repo_url" ] && [ -z "$_bk_input_type" ]; then
    _bk_input_verification_status="covered_by_source_commit"
  elif [ -z "$_bk_input_repo_url" ] \
    && [ -z "$_bk_input_path" ] \
    && [ -z "$_bk_input_type" ] \
    && { [ -n "$_bk_input_command" ] || [ "$_bk_input_has_parameters" -eq 1 ]; }; then
    _bk_input_verification_status="self_contained"
  else
    _bk_input_verification_status="declared"
  fi

  if [ -z "$_bk_input_dataset_version" ] && [ -n "$_bk_input_ref" ]; then
    _bk_input_dataset_version="$_bk_input_ref"
  fi
  if [ -z "$_bk_input_parameter_set_id" ] && [ -n "$_bk_input_command" ]; then
    _bk_input_parameter_set_id="runtime-parameters"
  fi
  if [ -z "$_bk_input_dataset_id" ]; then
    if [ -n "$_bk_input_command" ] || [ "$_bk_input_has_parameters" -eq 1 ]; then
      _bk_input_dataset_id="runtime-parameters-${_bk_input_parameter_set_id:-inline}"
    else
      echo "bk_record_input: --dataset-id is required for file or repository inputs" >&2
      return 1
    fi
  fi

  if [ "$_bk_input_verify_requested" -eq 1 ]; then
    case "$_bk_input_type" in
      file|matrix|archive|tar|tgz) ;;
      *)
        echo "bk_record_input: file verification requires --type file, matrix, or archive" >&2
        return 1
        ;;
    esac
    if [ -z "$_bk_input_verify_file" ] || [ -z "$_bk_input_expected_sha256" ] \
      || ! [[ "$_bk_input_expected_size_bytes" =~ ^(0|[1-9][0-9]*)$ ]]; then
      echo "bk_record_input: verification requires a file, SHA-256, and nonnegative byte count" >&2
      return 1
    fi
    _bk_input_expected_sha256="$(bk_lower_hex "$_bk_input_expected_sha256")"
    bk_validate_hex_length "$_bk_input_expected_sha256" 64 "input sha256" || return 1
    if _bk_observe_input_file "$_bk_input_verify_file"; then
      collection_status=recorded
      _bk_input_verification_status=mismatch
      if [[ "$_bk_input_actual_size" = "$_bk_input_expected_size_bytes" \
        && "$_bk_input_actual_sha256" = "$_bk_input_expected_sha256" ]]; then
        _bk_input_verification_status=verified
      else
        echo 'bk_record_input: input differs from reference; observed content recorded' >&2
      fi
    else
      collection_status=unavailable
      collection_error=collection_failed
      _bk_input_verification_status=unavailable
      _bk_input_actual_sha256="" _bk_input_actual_size=""
      echo 'bk_record_input: input observation unavailable; execution may continue' >&2
    fi
  fi

  _bk_input_call=(
    --dataset-id "$_bk_input_dataset_id"
    --kind "$_bk_input_kind"
    --source "$_bk_input_source"
    --verification-status "$_bk_input_verification_status"
  )
  if [ "$_bk_input_verify_requested" -eq 1 ]; then
    _bk_input_call+=(--collection-status "$collection_status" --collection-error "$collection_error")
    if [ "$collection_status" = recorded ]; then
      _bk_input_call+=(--sha256 "$_bk_input_actual_sha256" --size-bytes "$_bk_input_actual_size")
    fi
  fi
  if [ -n "$_bk_input_dataset_version" ]; then
    _bk_input_call+=(--dataset-version "$_bk_input_dataset_version")
  fi
  if [ -n "$_bk_input_parameter_set_id" ]; then
    _bk_input_call+=(--parameter-set-id "$_bk_input_parameter_set_id")
  fi
  if [ -n "$_bk_input_result_exp" ]; then
    _bk_input_call+=(--result-exp "$_bk_input_result_exp")
  fi
  if [ -n "$_bk_input_path" ]; then
    _bk_input_call+=(--repo-relative-path "$_bk_input_path")
  fi
  if [ -n "$_bk_input_repo_url" ]; then
    _bk_input_call+=(--source-url "$_bk_input_repo_url")
  fi
  if [ -n "$_bk_input_ref" ]; then
    _bk_input_call+=(--source-ref "$_bk_input_ref")
  fi
  if [ -n "$_bk_input_commit" ]; then
    _bk_input_call+=(--resolved-commit "$_bk_input_commit")
  fi
  if [ -n "$_bk_input_recipe" ]; then
    _bk_input_call+=(--recipe "$_bk_input_recipe")
  fi
  _bk_input_call+=("${_bk_input_parameter_args[@]}")
  _bk_input_call+=("${observation_args[@]}")
  if [ -n "$_bk_input_command" ]; then
    _bk_input_call+=(--command "$_bk_input_command" -- "${_bk_input_arguments[@]}")
  fi

  _bk_record_input_item "${_bk_input_call[@]}"
}

_bk_observe_input_file() {
  local path before after
  path=$(realpath -e -- "$1" 2>/dev/null) || return 1
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  before=$(stat -Lc '%d:%i:%f:%s:%y:%z' -- "$path" 2>/dev/null) || return 1
  _bk_input_actual_size=$(stat -Lc '%s' -- "$path" 2>/dev/null) || return 1
  # Bounded, nonblocking reads prevent a replacement FIFO or growing file from hanging collection.
  _bk_input_actual_sha256=$(
    set -o pipefail
    dd if="$path" iflag=nofollow,nonblock,count_bytes count="$_bk_input_actual_size" status=none 2>/dev/null |
      bk_sha256_file /dev/stdin
  ) || return 1
  [[ "$_bk_input_actual_sha256" =~ ^[0-9a-f]{64}$ ]] || return 1
  after=$(stat -Lc '%d:%i:%f:%s:%y:%z' -- "$path" 2>/dev/null) || return 1
  [ "$before" = "$after" ]
}

bk_record_runtime_parameter_input() {
  bk_record_input "$@"
}

bk_reset_timing_observations() {
  _bk_reset_timing_file="${BK_TIMING_OBSERVATIONS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/timing_observations.json}"
  _bk_reset_timing_items_file="${BK_TIMING_OBSERVATION_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.timing_observation_items.jsonl}"
  rm -f "$_bk_reset_timing_file" "$_bk_reset_timing_items_file"
}

_bk_safe_timing_observation_artifact_path() {
  case "$1" in
    results/*.json) ;;
    *) return 1 ;;
  esac

  case "$1" in
    /*|*"/../"*|../*|*"/.."|*\\*) return 1 ;;
  esac
}

_bk_record_timing_observation_items_file() {
  _bk_timing_info_file="$1"
  _bk_timing_jsonl_file="$2"

  {
    printf '{\n'
    printf '  "schema_version": 1,\n'
    printf '  "observations": [\n'
    _bk_timing_first=1
    while IFS= read -r _bk_timing_item; do
      [ -n "$_bk_timing_item" ] || continue
      if [ "$_bk_timing_first" -eq 0 ]; then
        printf ',\n'
      fi
      printf '    %s' "$_bk_timing_item"
      _bk_timing_first=0
    done < "$_bk_timing_jsonl_file"
    printf '\n'
    printf '  ]\n'
    printf '}\n'
  } > "$_bk_timing_info_file"
}

# bk_record_timing_observation - Register an optional detailed timing artifact.
#
# Detailed timing observations are raw or lightly normalized measurement
# evidence. They are kept separate from SECTION/OVERLAP metadata, which is the
# current estimation-oriented projection of app timings.
bk_record_timing_observation() {
  local artifact_json item_json
  _bk_timing_id=""
  _bk_timing_kind="detailed-timing"
  _bk_timing_producer=""
  _bk_timing_format=""
  _bk_timing_result_exp=""
  _bk_timing_artifact_path=""
  _bk_timing_artifact_file=""
  _bk_timing_summary_json=""
  _bk_timing_note=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --id)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --id requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_id="$1"
        ;;
      --kind)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --kind requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_kind="$1"
        ;;
      --producer)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --producer requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_producer="$1"
        ;;
      --format)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --format requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_format="$1"
        ;;
      --result-exp)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --result-exp requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_result_exp="$1"
        ;;
      --artifact|--artifact-path)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: $1 requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_artifact_path="$1"
        ;;
      --artifact-file)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --artifact-file requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_artifact_file="$1"
        ;;
      --summary-json)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --summary-json requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_summary_json="$1"
        ;;
      --note)
        if [ $# -lt 2 ]; then
          echo "bk_record_timing_observation: --note requires a value" >&2
          return 1
        fi
        shift
        _bk_timing_note="$1"
        ;;
      *)
        echo "bk_record_timing_observation: unknown option: $1" >&2
        return 1
        ;;
    esac
    shift
  done

  if [ -z "$_bk_timing_artifact_path" ]; then
    echo "bk_record_timing_observation: --artifact is required" >&2
    return 1
  fi
  if ! _bk_safe_timing_observation_artifact_path "$_bk_timing_artifact_path"; then
    echo "bk_record_timing_observation: artifact must be a safe results/*.json path" >&2
    return 1
  fi

  if [ -z "$_bk_timing_artifact_file" ]; then
    _bk_timing_artifact_file="$_bk_timing_artifact_path"
  fi
  if [ ! -f "$_bk_timing_artifact_file" ]; then
    echo "bk_record_timing_observation: skipped missing artifact $_bk_timing_artifact_file" >&2
    return 0
  fi
  # Preserve the registration-time evidence; JSON interpretation belongs to the sender.
  if [ ! -r "$_bk_timing_artifact_file" ] || IFS= read -r -d '' artifact_json < "$_bk_timing_artifact_file"; then
    echo "bk_record_timing_observation: unreadable or binary artifact" >&2
    return 1
  fi
  if [ -z "$_bk_timing_id" ]; then
    _bk_timing_id=$(basename "$_bk_timing_artifact_path" .json)
  fi
  # shellcheck source=scripts/json_output.sh
  source "${BK_BENCHKIT_ROOT}/scripts/json_output.sh"
  item_json=$(bk_json_object string id "$_bk_timing_id" string kind "$_bk_timing_kind" \
    string producer "$_bk_timing_producer" string format "$_bk_timing_format" \
    string result_exp "$_bk_timing_result_exp" string note "$_bk_timing_note" \
    json artifact "$(bk_json_object string type file_reference string path "$_bk_timing_artifact_path")" \
    json timing_capture "$(bk_json_object json schema_version 1 string artifact_json "$artifact_json" \
      string summary_json "$_bk_timing_summary_json")") || return 1

  _bk_timing_info_file="${BK_TIMING_OBSERVATIONS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/timing_observations.json}"
  _bk_timing_items_file="${BK_TIMING_OBSERVATION_ITEMS_FILE:-${_BK_DEFAULT_RESULTS_DIR}/.timing_observation_items.jsonl}"
  _bk_initialize_metadata timing "$_bk_timing_info_file" "$_bk_timing_items_file" || return 1
  mkdir -p "$(dirname "$_bk_timing_info_file")" "$(dirname "$_bk_timing_items_file")" || return 1

  printf '%s\n' "$item_json" >> "$_bk_timing_items_file" || return 1

  _bk_record_timing_observation_items_file "$_bk_timing_info_file" "$_bk_timing_items_file"
}

# Write a compact, tool-neutral manifest for the profiler archive. Result JSON
# generation reads this manifest to expose summary fields without opening every
# raw profiler artifact. For fapp, run_events contains counter names; for ncu it
# carries the selected level so optional hooks still receive useful context.
bk_profiler_write_meta() {
  _bk_meta_stage_dir="$1"
  _bk_meta_tool="$2"
  _bk_meta_level="$3"
  _bk_meta_report_format="$4"
  _bk_meta_run_names="$5"
  _bk_meta_run_events="$6"
  _bk_meta_profiler_args="$7"
  _bk_meta_report_args="$8"
  _bk_meta_file="${_bk_meta_stage_dir}/meta.json"
  IFS=',' read -r -a _bk_meta_names <<< "$_bk_meta_run_names"
  IFS=',' read -r -a _bk_meta_events <<< "$_bk_meta_run_events"

  {
    printf '{\n'
    printf '  "tool": "%s",\n' "$_bk_meta_tool"
    printf '  "level": "%s",\n' "$_bk_meta_level"
    printf '  "report_format": "%s",\n' "$_bk_meta_report_format"
    printf '  "raw_dir": "raw",\n'
    printf '  "measurement": {\n'
    printf '    "run_count": %s,\n' "${#_bk_meta_names[@]}"
    printf '    "profiler_args": '
    bk_json_string "$_bk_meta_profiler_args"
    printf ',\n'
    printf '    "report_args": '
    bk_json_string "$_bk_meta_report_args"
    case "$_bk_meta_tool" in
      fapp)
        printf ',\n'
        printf '    "fapp_events": '
        bk_json_string_array "${_bk_meta_events[@]}"
        printf '\n'
        ;;
      ncu)
        _bk_meta_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_meta_level")
        read -r -a _bk_meta_ncu_level_arg_array <<< "$_bk_meta_ncu_level_args"
        printf ',\n'
        printf '    "ncu_options": '
        bk_json_string_array "--target-processes" "all" "${_bk_meta_ncu_level_arg_array[@]}"
        printf '\n'
        ;;
      *)
        printf '\n'
        ;;
    esac
    printf '  },\n'
    printf '  "runs": [\n'
    for _bk_meta_idx in "${!_bk_meta_names[@]}"; do
      _bk_meta_name="${_bk_meta_names[$_bk_meta_idx]}"
      _bk_meta_event="${_bk_meta_events[$_bk_meta_idx]:-}"
      case "$_bk_meta_tool" in
        fapp)
          _bk_meta_text_path="reports/fapp_A_${_bk_meta_name}.txt"
          _bk_meta_csv_path="reports/cpu_pa_${_bk_meta_name}.csv"
          _bk_meta_text_abs="${_bk_meta_stage_dir}/${_bk_meta_text_path}"
          _bk_meta_csv_abs="${_bk_meta_stage_dir}/${_bk_meta_csv_path}"
          _bk_meta_ncu_report_path=""
          _bk_meta_ncu_report_abs=""
          ;;
        ncu)
          _bk_meta_text_path="reports/ncu_import_${_bk_meta_name}.txt"
          _bk_meta_csv_path=""
          _bk_meta_text_abs="${_bk_meta_stage_dir}/${_bk_meta_text_path}"
          _bk_meta_csv_abs=""
          _bk_meta_ncu_report_abs=$(bk_profiler_find_ncu_report "${_bk_meta_stage_dir}/raw/${_bk_meta_name}" || true)
          if [ -n "$_bk_meta_ncu_report_abs" ]; then
            _bk_meta_ncu_report_path="${_bk_meta_ncu_report_abs#${_bk_meta_stage_dir}/}"
          else
            _bk_meta_ncu_report_path=""
          fi
          _bk_meta_ncu_raw_csv_path="raw/${_bk_meta_name}/profile_raw.csv"
          _bk_meta_ncu_raw_csv_abs="${_bk_meta_stage_dir}/${_bk_meta_ncu_raw_csv_path}"
          ;;
        *)
          _bk_meta_text_path=""
          _bk_meta_csv_path=""
          _bk_meta_text_abs=""
          _bk_meta_csv_abs=""
          _bk_meta_ncu_report_path=""
          _bk_meta_ncu_report_abs=""
          ;;
      esac

      printf '    {\n'
      printf '      "name": "%s",\n' "$_bk_meta_name"
      printf '      "event": "%s",\n' "$_bk_meta_event"
      printf '      "raw_path": "raw/%s",\n' "$_bk_meta_name"
      printf '      "measurement": {\n'
      case "$_bk_meta_tool" in
        fapp)
          printf '        "counter": '
          bk_json_string "$_bk_meta_event"
          printf ',\n'
          printf '        "options": '
          bk_json_string_array "-C" "-d" "raw/${_bk_meta_name}" "-Hevent=${_bk_meta_event}"
          printf '\n'
          ;;
        ncu)
          _bk_meta_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_meta_level")
          read -r -a _bk_meta_ncu_level_arg_array <<< "$_bk_meta_ncu_level_args"
          printf '        "options": '
          bk_json_string_array "-o" "raw/${_bk_meta_name}/profile" "--target-processes" "all" "${_bk_meta_ncu_level_arg_array[@]}"
          printf '\n'
          ;;
        *)
          printf '        "options": []\n'
          ;;
      esac
      printf '      },\n'
      printf '      "reports": [\n'
      _bk_meta_has_report=0
      if [ -f "$_bk_meta_text_abs" ]; then
        printf '        {"kind": "summary_text", "path": "%s"}' "$_bk_meta_text_path"
        _bk_meta_has_report=1
      fi
      if [ -f "$_bk_meta_csv_abs" ]; then
        if [ "$_bk_meta_has_report" -eq 1 ]; then
          printf ',\n'
        fi
        printf '        {"kind": "cpu_pa_csv", "path": "%s"}' "$_bk_meta_csv_path"
        _bk_meta_has_report=1
      fi
      if [ -n "$_bk_meta_ncu_report_path" ] && [ -f "$_bk_meta_ncu_report_abs" ]; then
        if [ "$_bk_meta_has_report" -eq 1 ]; then
          printf ',\n'
        fi
        printf '        {"kind": "ncu_report", "path": "%s"}' "$_bk_meta_ncu_report_path"
        _bk_meta_has_report=1
      fi
      if [ "${_bk_meta_tool}" = "ncu" ] && [ -f "${_bk_meta_ncu_raw_csv_abs:-}" ]; then
        if [ "$_bk_meta_has_report" -eq 1 ]; then
          printf ',\n'
        fi
        printf '        {"kind": "ncu_raw_csv", "path": "%s"}' "$_bk_meta_ncu_raw_csv_path"
        _bk_meta_has_report=1
      fi
      if [ "$_bk_meta_has_report" -eq 1 ]; then
        printf '\n'
      fi
      printf '      ]\n'
      if [ "$_bk_meta_idx" -lt "$(( ${#_bk_meta_names[@]} - 1 ))" ]; then
        printf '    },\n'
      else
        printf '    }\n'
      fi
    done
    printf '  ]\n'
    printf '}\n'
  } > "$_bk_meta_file"
}

# Optional hooks let site scripts wrap individual profiler runs, for example to
# load per-run modules or print scheduler diagnostics. Hook arguments are:
# tool, level, run name, fapp event or ncu level, then the profiled command.
bk_profiler_call_optional_hook() {
  _bk_hook_name="$1"
  shift || true

  if declare -F "$_bk_hook_name" >/dev/null 2>&1; then
    "$_bk_hook_name" "$@"
  fi
}






bk_write_gpu_kernel_profile_metadata() {
  [ "$#" -ge 8 ] && [ "$#" -le 9 ] || return 2
  local path="$1" archive="$2" section="$3" name="$4" slug="$5" kernel="$6"
  local skip="$7" count="$8" discovery="${9:-}" temporary
  [[ "$skip" =~ ^(0|[1-9][0-9]*)$ && "$count" =~ ^[1-9][0-9]*$ ]] || {
    echo 'bk_write_gpu_kernel_profile_metadata: invalid launch window' >&2
    return 1
  }
  [ -n "$discovery" ] || discovery='{}'
  # shellcheck source=scripts/json_output.sh
  source "${BK_BENCHKIT_ROOT}/scripts/json_output.sh"
  mkdir -p "$(dirname -- "$path")" || return 1
  temporary=$(mktemp "${path}.tmp.XXXXXX") || return 1
  # Capture discovery verbatim; consumers with a JSON runtime interpret it later.
  if bk_json_object json schema_version 2 string kind gpu_kernel_profile_metadata \
      string profiler ncu string section "$section" string profile_name "$name" \
      string profile_slug "$slug" string artifact_path "$archive" \
      json ncu "$(bk_json_object string kernel_regex "$kernel" json launch_skip "$skip" json launch_count "$count")" \
      string nsys_discovery_json "$discovery" > "$temporary" && mv -- "$temporary" "$path"; then
    return 0
  fi
  rm -f -- "$temporary"
  return 1
}

bk_run_ncu_acquisition_profile() {
  _bk_ncu_profile_name=""
  _bk_ncu_profile_slug=""
  _bk_ncu_kernel_regex=""
  _bk_ncu_launch_skip=""
  _bk_ncu_launch_count=""
  _bk_ncu_level="${BK_PROFILER_LEVEL:-detailed}"
  _bk_ncu_archive=""
  _bk_ncu_archive_rel=""
  _bk_ncu_raw_dir=""
  _bk_ncu_log=""
  _bk_ncu_section=""
  _bk_ncu_metadata=""
  _bk_ncu_discovery_json="{}"

  while [ $# -gt 0 ]; do
    case "$1" in
      --profile-name) shift; _bk_ncu_profile_name="${1:-}" ;;
      --profile-slug) shift; _bk_ncu_profile_slug="${1:-}" ;;
      --kernel-regex) shift; _bk_ncu_kernel_regex="${1:-}" ;;
      --launch-skip) shift; _bk_ncu_launch_skip="${1:-}" ;;
      --launch-count) shift; _bk_ncu_launch_count="${1:-}" ;;
      --level) shift; _bk_ncu_level="${1:-}" ;;
      --archive) shift; _bk_ncu_archive="${1:-}" ;;
      --archive-rel) shift; _bk_ncu_archive_rel="${1:-}" ;;
      --raw-dir) shift; _bk_ncu_raw_dir="${1:-}" ;;
      --log) shift; _bk_ncu_log="${1:-}" ;;
      --section) shift; _bk_ncu_section="${1:-}" ;;
      --metadata) shift; _bk_ncu_metadata="${1:-}" ;;
      --discovery-json)
        shift
        _bk_ncu_discovery_json="${1:-}"
        if [ -z "$_bk_ncu_discovery_json" ]; then
          _bk_ncu_discovery_json="{}"
        fi
        ;;
      --)
        shift
        break
        ;;
      *)
        echo "bk_run_ncu_acquisition_profile: unknown argument '$1'" >&2
        return 1
        ;;
    esac
    shift
  done

  if [ $# -eq 0 ]; then
    echo "bk_run_ncu_acquisition_profile: requires command after --" >&2
    return 1
  fi
  if [ -z "$_bk_ncu_profile_name" ] || [ -z "$_bk_ncu_kernel_regex" ] || [ -z "$_bk_ncu_launch_skip" ] || [ -z "$_bk_ncu_launch_count" ]; then
    echo "bk_run_ncu_acquisition_profile: profile name, kernel regex, launch skip, and launch count are required" >&2
    return 1
  fi

  _bk_ncu_profile_slug="${_bk_ncu_profile_slug:-$(bk_profile_slug "$_bk_ncu_profile_name")}"
  _bk_ncu_archive="${_bk_ncu_archive:-results/padata_${_bk_ncu_profile_slug}.tgz}"
  _bk_ncu_archive_rel="${_bk_ncu_archive_rel:-$_bk_ncu_archive}"
  _bk_ncu_raw_dir="${_bk_ncu_raw_dir:-ncu_${_bk_ncu_profile_slug}}"
  _bk_ncu_metadata="${_bk_ncu_metadata:-${_bk_ncu_archive%.tgz}.metadata.json}"

  _bk_ncu_old_profiler_args="${BK_PROFILER_ARGS:-}"
  _bk_ncu_old_profiler_raw_csv="${BK_PROFILER_NCU_RAW_CSV:-}"
  _bk_ncu_had_profiler_args=0
  _bk_ncu_had_profiler_raw_csv=0
  _bk_ncu_had_errexit=0
  if [ "${BK_PROFILER_ARGS+x}" ]; then
    _bk_ncu_had_profiler_args=1
  fi
  if [ "${BK_PROFILER_NCU_RAW_CSV+x}" ]; then
    _bk_ncu_had_profiler_raw_csv=1
  fi
  case "$-" in
    *e*) _bk_ncu_had_errexit=1 ;;
  esac

  export BK_PROFILER_ARGS="--kernel-name-base demangled --kernel-name ${_bk_ncu_kernel_regex} --launch-skip ${_bk_ncu_launch_skip} --launch-count ${_bk_ncu_launch_count}"
  export BK_PROFILER_NCU_RAW_CSV=true

  echo "bk_run_ncu_acquisition_profile: profile='${_bk_ncu_profile_name}' kernel='${_bk_ncu_kernel_regex}' skip=${_bk_ncu_launch_skip} count=${_bk_ncu_launch_count}" >&2
  set +e
  if [ -n "$_bk_ncu_log" ]; then
    bk_profiler ncu \
      --level "$_bk_ncu_level" \
      --archive "$_bk_ncu_archive" \
      --raw-dir "$_bk_ncu_raw_dir" \
      -- "$@" </dev/null 2>&1 | tee "$_bk_ncu_log"
    _bk_ncu_status=${PIPESTATUS[0]}
  else
    bk_profiler ncu \
      --level "$_bk_ncu_level" \
      --archive "$_bk_ncu_archive" \
      --raw-dir "$_bk_ncu_raw_dir" \
      -- "$@"
    _bk_ncu_status=$?
  fi
  if [ "$_bk_ncu_had_errexit" -eq 1 ]; then
    set -e
  else
    set +e
  fi

  if [ "$_bk_ncu_had_profiler_args" -eq 1 ]; then
    export BK_PROFILER_ARGS="$_bk_ncu_old_profiler_args"
  else
    unset BK_PROFILER_ARGS
  fi
  if [ "$_bk_ncu_had_profiler_raw_csv" -eq 1 ]; then
    export BK_PROFILER_NCU_RAW_CSV="$_bk_ncu_old_profiler_raw_csv"
  else
    unset BK_PROFILER_NCU_RAW_CSV
  fi

  if [ "$_bk_ncu_status" -ne 0 ]; then
    echo "bk_run_ncu_acquisition_profile: profile '${_bk_ncu_profile_name}' failed with status ${_bk_ncu_status}" >&2
    return "$_bk_ncu_status"
  fi

  if [ -n "$_bk_ncu_section" ]; then
    bk_write_gpu_kernel_profile_metadata \
      "$_bk_ncu_metadata" \
      "$_bk_ncu_archive_rel" \
      "$_bk_ncu_section" \
      "$_bk_ncu_profile_name" \
      "$_bk_ncu_profile_slug" \
      "$_bk_ncu_kernel_regex" \
      "$_bk_ncu_launch_skip" \
      "$_bk_ncu_launch_count" \
      "$_bk_ncu_discovery_json" || return $?
    echo "bk_run_ncu_acquisition_profile: metadata ${_bk_ncu_metadata}" >&2
  fi
}

bk_profiler() {
  local BK_RUN_RESULTS_DIR="${BK_RUN_RESULTS_DIR:-}"
  local _bk_workflow_profile
  if [ $# -lt 2 ]; then
    echo "bk_profiler: requires a profiler tool and an execution command" >&2
    return 1
  fi

  _bk_profiler_tool=$(bk_get_profiler_tool "$1") || return 1
  shift
  _bk_profiler_archive="${BK_PROFILER_ARCHIVE:-results/padata.tgz}"
  _bk_profiler_dir="${BK_PROFILER_DIR:-pa}"
  _bk_profiler_level="${BK_PROFILER_LEVEL:-}"
  _bk_profiler_report_format="${BK_PROFILER_REPORT_FORMAT:-}"

  while [ $# -gt 0 ]; do
    case "$1" in
      --level)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --level requires a value" >&2
          return 1
        fi
        _bk_profiler_level="$1"
        ;;
      --report-format)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --report-format requires a value" >&2
          return 1
        fi
        _bk_profiler_report_format="$1"
        ;;
      --archive)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --archive requires a value" >&2
          return 1
        fi
        _bk_profiler_archive="$1"
        ;;
      --raw-dir)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --raw-dir requires a value" >&2
          return 1
        fi
        _bk_profiler_dir="$1"
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
    shift
  done

  if [ $# -eq 0 ]; then
    echo "bk_profiler: requires an execution command" >&2
    return 1
  fi

  BK_RUN_RESULTS_DIR="${BK_RUN_RESULTS_DIR:-$(dirname "$_bk_profiler_archive")}"
  if [ -z "$_bk_profiler_tool" ]; then
    bk_run -- "$@"
    return $?
  fi

  _bk_workflow_profile=$(basename "$_bk_profiler_archive" .tgz)

  _bk_profiler_level=$(bk_get_profiler_level "$_bk_profiler_tool" "$_bk_profiler_level") || return 1
  _bk_profiler_report_format=$(bk_get_profiler_report_format "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_profiler_report_format") || return 1

  rm -rf "$_bk_profiler_dir"
  mkdir -p "$_bk_profiler_dir"

  _bk_stage_dir="${BK_PROFILER_STAGE_DIR:-bk_profiler_artifact}"
  rm -rf "$_bk_stage_dir"
  mkdir -p "$_bk_stage_dir"
  mkdir -p "$_bk_stage_dir/raw"
  mkdir -p "$_bk_stage_dir/reports"
  _bk_profiler_run_names=""
  _bk_profiler_run_events=""
  _bk_profiler_status=0
  _bk_profiler_extra_args="${BK_PROFILER_ARGS:-}"
  _bk_profiler_report_extra_args="${BK_PROFILER_REPORT_ARGS:-}"

  case "$_bk_profiler_tool" in
    fapp)
      export FLIB_FASTOMP="${FLIB_FASTOMP:-TRUE}"
      read -r -a _bk_fapp_events <<< "$(bk_profiler_fapp_level_events "$_bk_profiler_level")"
      _bk_fapp_run_index=1
      for _bk_fapp_event in "${_bk_fapp_events[@]}"; do
        _bk_fapp_rep_name="rep${_bk_fapp_run_index}"
        _bk_fapp_rep_dir="${_bk_profiler_dir}/${_bk_fapp_rep_name}"
        mkdir -p "$_bk_fapp_rep_dir"
        echo "bk_profiler[fapp]: starting ${_bk_fapp_rep_name} event=${_bk_fapp_event}" >&2
        bk_profiler_call_optional_hook bk_profiler_before_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_fapp_rep_name" "$_bk_fapp_event" "$@" || return 1
        # BK_PROFILER_ARGS is intentionally word-split into fapp options.
        # shellcheck disable=SC2086
        if bk_profile_execute --tool fapp --profile "${_bk_workflow_profile}/${_bk_fapp_rep_name}/${_bk_fapp_event}" -- \
          fapp -C -d "$_bk_fapp_rep_dir" ${_bk_profiler_extra_args} -Hevent="${_bk_fapp_event}" "$@"; then
          _bk_fapp_status=0
        else
          _bk_fapp_status=$?
        fi
        bk_profiler_call_optional_hook bk_profiler_after_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_fapp_rep_name" "$_bk_fapp_event" "$@" || return 1
        if [ "$_bk_fapp_status" -eq 0 ]; then
          echo "bk_profiler[fapp]: completed ${_bk_fapp_rep_name} event=${_bk_fapp_event}" >&2
        else
          echo "bk_profiler[fapp]: failed ${_bk_fapp_rep_name} event=${_bk_fapp_event} status=${_bk_fapp_status}" >&2
          _bk_profiler_status="$_bk_fapp_status"
        fi
        cp -R "$_bk_fapp_rep_dir" "$_bk_stage_dir/raw/${_bk_fapp_rep_name}"
        if [ -n "$_bk_profiler_run_names" ]; then
          _bk_profiler_run_names="${_bk_profiler_run_names},${_bk_fapp_rep_name}"
          _bk_profiler_run_events="${_bk_profiler_run_events},${_bk_fapp_event}"
        else
          _bk_profiler_run_names="${_bk_fapp_rep_name}"
          _bk_profiler_run_events="${_bk_fapp_event}"
        fi
        _bk_fapp_run_index=$((_bk_fapp_run_index + 1))
        if [ "$_bk_fapp_status" -ne 0 ]; then
          break
        fi
      done
      ;;
    ncu)
      if ! command -v ncu >/dev/null 2>&1; then
        echo "bk_profiler[ncu]: ncu not found in PATH" >&2
        return 1
      fi
      _bk_ncu_rep_name="rep1"
      _bk_ncu_rep_dir="${_bk_profiler_dir}/${_bk_ncu_rep_name}"
      _bk_ncu_profile_base="${_bk_ncu_rep_dir}/profile"
      mkdir -p "$_bk_ncu_rep_dir"
      _bk_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_profiler_level") || return 1
      echo "bk_profiler[ncu]: starting ${_bk_ncu_rep_name} level=${_bk_profiler_level}" >&2
      bk_profiler_call_optional_hook bk_profiler_before_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_ncu_rep_name" "$_bk_profiler_level" "$@" || return 1
      # BK_PROFILER_ARGS is intentionally word-split into ncu options.
      # shellcheck disable=SC2086
      if bk_profile_execute --tool ncu --profile "${_bk_workflow_profile}/${_bk_ncu_rep_name}" -- \
        ncu -o "$_bk_ncu_profile_base" --target-processes all ${_bk_ncu_level_args} ${_bk_profiler_extra_args} "$@"; then
        _bk_profiler_status=0
      else
        _bk_profiler_status=$?
      fi
      bk_profiler_call_optional_hook bk_profiler_after_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_ncu_rep_name" "$_bk_profiler_level" "$@" || return 1
      if [ "$_bk_profiler_status" -eq 0 ]; then
        echo "bk_profiler[ncu]: completed ${_bk_ncu_rep_name} level=${_bk_profiler_level}" >&2
      else
        echo "bk_profiler[ncu]: failed ${_bk_ncu_rep_name} level=${_bk_profiler_level} status=${_bk_profiler_status}" >&2
      fi
      case "${BK_PROFILER_NCU_RAW_CSV:-false}" in
        1|true|TRUE|yes|YES|on|ON)
          _bk_ncu_report_file=$(bk_profiler_find_ncu_report "$_bk_ncu_rep_dir" || true)
          if [ -n "$_bk_ncu_report_file" ]; then
            bk_profile_execute --tool ncu --phase export --profile "${_bk_workflow_profile}/${_bk_ncu_rep_name}/raw" -- \
              ncu --import "$_bk_ncu_report_file" \
              --page raw \
              --csv \
              --print-units base \
              --print-fp \
              > "${_bk_ncu_rep_dir}/profile_raw.csv" 2> "${_bk_ncu_rep_dir}/profile_raw.csv.log" || true
          fi
          ;;
      esac
      cp -R "$_bk_ncu_rep_dir" "$_bk_stage_dir/raw/${_bk_ncu_rep_name}"
      case "${BK_PROFILER_ARCHIVE_NCU_REPORT:-false}" in
        1|true|TRUE|yes|YES|on|ON) ;;
        *)
          find "$_bk_stage_dir/raw/${_bk_ncu_rep_name}" -maxdepth 1 -type f \( \
            -name '*.ncu-rep' -o \
            -name '*.nsight-cuprof' \
          \) -delete
          ;;
      esac
      _bk_profiler_run_names="${_bk_ncu_rep_name}"
      _bk_profiler_run_events="${_bk_profiler_level}"
      ;;
  esac

  # Report import/postprocess is best-effort: keep the raw archive even when a
  # text/CSV summary cannot be produced on the run node.
  case "$_bk_profiler_tool" in
    fapp)
      if _bk_fapp_post_cmd=$(bk_profiler_fapp_postprocess_command); then
        export FLIB_FASTOMP="${FLIB_FASTOMP:-TRUE}"
        IFS=',' read -r -a _bk_fapp_run_name_list <<< "$_bk_profiler_run_names"
        for _bk_fapp_rep_name in "${_bk_fapp_run_name_list[@]}"; do
          _bk_fapp_rep_dir="${_bk_profiler_dir}/${_bk_fapp_rep_name}"
          if [ "$_bk_profiler_report_format" = "text" ] || [ "$_bk_profiler_report_format" = "both" ]; then
            # BK_PROFILER_REPORT_ARGS is intentionally word-split into fapp/fapppx options.
            # shellcheck disable=SC2086
            bk_profile_execute --tool fapp --phase export --profile "${_bk_workflow_profile}/${_bk_fapp_rep_name}/text" -- \
              "$_bk_fapp_post_cmd" -A -d "$_bk_fapp_rep_dir" ${_bk_profiler_report_extra_args} > "$_bk_stage_dir/reports/fapp_A_${_bk_fapp_rep_name}.txt" 2>&1 || true
          fi
          if [ "$_bk_profiler_report_format" = "csv" ] || [ "$_bk_profiler_report_format" = "both" ]; then
            # BK_PROFILER_REPORT_ARGS is intentionally word-split into fapp/fapppx options.
            # shellcheck disable=SC2086
            bk_profile_execute --tool fapp --phase export --profile "${_bk_workflow_profile}/${_bk_fapp_rep_name}/csv" -- \
              "$_bk_fapp_post_cmd" -A -d "$_bk_fapp_rep_dir" ${_bk_profiler_report_extra_args} -Icpupa -tcsv -o "$_bk_stage_dir/reports/cpu_pa_${_bk_fapp_rep_name}.csv" >/dev/null 2>&1 || true
          fi
        done
      else
        echo "fapp/fapppx not found in PATH" > "$_bk_stage_dir/reports/fapp_A_missing.txt"
      fi
      ;;
    ncu)
      IFS=',' read -r -a _bk_ncu_run_name_list <<< "$_bk_profiler_run_names"
      for _bk_ncu_rep_name in "${_bk_ncu_run_name_list[@]}"; do
        _bk_ncu_report_file=$(bk_profiler_find_ncu_report "$_bk_profiler_dir/${_bk_ncu_rep_name}" || true)
        if [ -n "$_bk_ncu_report_file" ] && { [ "$_bk_profiler_report_format" = "text" ] || [ "$_bk_profiler_report_format" = "both" ]; }; then
          # BK_PROFILER_REPORT_ARGS is intentionally word-split into ncu --import options.
          # shellcheck disable=SC2086
          bk_profile_execute --tool ncu --phase export --profile "${_bk_workflow_profile}/${_bk_ncu_rep_name}/details" -- \
            ncu --import "$_bk_ncu_report_file" --page details ${_bk_profiler_report_extra_args} > "$_bk_stage_dir/reports/ncu_import_${_bk_ncu_rep_name}.txt" 2>&1 || true
        fi
      done
      ;;
  esac

  # Preserve the profiler command status after metadata/archive creation. If the
  # archive itself cannot be written, that failure is more actionable to CI.
  bk_profiler_write_meta "$_bk_stage_dir" "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_profiler_report_format" "$_bk_profiler_run_names" "$_bk_profiler_run_events" "$_bk_profiler_extra_args" "$_bk_profiler_report_extra_args"
  if tar -czf "$_bk_profiler_archive" -C "$(dirname "$_bk_stage_dir")" "$(basename "$_bk_stage_dir")"; then
    _bk_profiler_archive_status=0
  else
    _bk_profiler_archive_status=$?
  fi
  rm -rf "$_bk_stage_dir"
  if [ "$_bk_profiler_archive_status" -ne 0 ]; then
    return "$_bk_profiler_archive_status"
  fi
  return "$_bk_profiler_status"
}













# shellcheck source=scripts/profiling/acquisition.sh
source "${BK_BENCHKIT_ROOT}/scripts/profiling/acquisition.sh"

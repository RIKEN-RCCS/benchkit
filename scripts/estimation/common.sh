#!/bin/bash
# common.sh — Common function library for performance estimation
#
# Provides shared variables and functions used by application-specific
# estimate scripts (programs/<code>/estimate.sh).
#
# Usage:
#   source scripts/estimation/common.sh

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../result_server/api.sh"

# ---------------------------------------------------------------------------
# Global variables — populated by read_values
# ---------------------------------------------------------------------------
est_code=""
est_exp=""
est_fom=""
est_system=""
est_node_count=""
est_numproc_node=""
est_timestamp=""
est_uuid=""

# ---------------------------------------------------------------------------
# Global variables — set by application-specific estimate scripts,
# consumed by print_json
# ---------------------------------------------------------------------------
est_current_system=""
est_current_fom=""
est_current_target_nodes=""
est_current_scaling_method=""
est_future_system=""
est_future_fom=""
est_future_target_nodes=""
est_future_scaling_method=""
est_current_model_json=""
est_future_model_json=""

# Benchmark sub-object variables for current_system
est_current_bench_system=""
est_current_bench_fom=""
est_current_bench_nodes=""
est_current_bench_numproc_node=""
est_current_bench_timestamp=""
est_current_bench_uuid=""

# Benchmark sub-object variables for future_system
est_future_bench_system=""
est_future_bench_fom=""
est_future_bench_nodes=""
est_future_bench_numproc_node=""
est_future_bench_timestamp=""
est_future_bench_uuid=""

# Raw input / fetched Result JSON fragments (optional)
est_input_fom_breakdown=""

# fom_breakdown JSON strings (optional, set by estimate scripts)
est_current_fom_breakdown=""
est_future_fom_breakdown=""

# Optional top-level metadata blocks for extended Estimate JSON
est_estimation_id=""
est_estimation_timestamp=""
est_method_class=""
est_detail_level=""
est_source_result_uuid=""
est_estimation_package=""
est_estimation_package_version=""
est_requested_estimation_package=""
est_requested_estimation_package_version=""
est_current_estimation_package=""
est_current_estimation_package_version=""
est_requested_current_estimation_package=""
est_requested_current_estimation_package_version=""
est_future_estimation_package=""
est_future_estimation_package_version=""
est_requested_future_estimation_package=""
est_requested_future_estimation_package_version=""
est_measurement_json=""
est_assumptions_json=""
est_input_artifacts_json=""
est_model_json=""
est_applicability_json=""
est_confidence_json=""
est_notes_json=""
est_reestimation_json=""

_bk_normalize_estimation_timestamp() {
  local raw="${1:-}"

  if [[ -z "$raw" ]]; then
    echo ""
    return 0
  fi

  if [[ "$raw" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
    echo "${raw:0:4}-${raw:4:2}-${raw:6:2} ${raw:9:2}:${raw:11:2}:${raw:13:2}"
    return 0
  fi

  echo "$raw"
}

load_reestimation_context() {
  local context_file="results/reestimation_context.json"

  if [[ ! -f "$context_file" ]]; then
    est_reestimation_json=""
    return 0
  fi

  est_reestimation_json=$(jq -c '.' "$context_file")
}

bk_estimation_apply_declared_defaults() {
  BK_ESTIMATION_CURRENT_PACKAGE="${BK_ESTIMATION_CURRENT_PACKAGE:-${BK_ESTIMATION_DECLARED_CURRENT_PACKAGE:-}}"
  BK_ESTIMATION_FUTURE_PACKAGE="${BK_ESTIMATION_FUTURE_PACKAGE:-${BK_ESTIMATION_DECLARED_FUTURE_PACKAGE:-}}"
  BK_ESTIMATION_BASELINE_SYSTEM="${BK_ESTIMATION_BASELINE_SYSTEM:-${BK_ESTIMATION_DECLARED_BASELINE_SYSTEM:-}}"
  BK_ESTIMATION_BASELINE_EXP="${BK_ESTIMATION_BASELINE_EXP:-${BK_ESTIMATION_DECLARED_BASELINE_EXP:-}}"
  BK_ESTIMATION_FUTURE_SYSTEM="${BK_ESTIMATION_FUTURE_SYSTEM:-${BK_ESTIMATION_DECLARED_FUTURE_SYSTEM:-}}"
  BK_ESTIMATION_CURRENT_TARGET_NODES="${BK_ESTIMATION_CURRENT_TARGET_NODES:-${BK_ESTIMATION_DECLARED_CURRENT_TARGET_NODES:-}}"
  BK_ESTIMATION_FUTURE_TARGET_NODES="${BK_ESTIMATION_FUTURE_TARGET_NODES:-${BK_ESTIMATION_DECLARED_FUTURE_TARGET_NODES:-}}"
  export BK_ESTIMATION_CURRENT_PACKAGE
  export BK_ESTIMATION_FUTURE_PACKAGE
  export BK_ESTIMATION_BASELINE_SYSTEM
  export BK_ESTIMATION_BASELINE_EXP
  export BK_ESTIMATION_FUTURE_SYSTEM
  export BK_ESTIMATION_CURRENT_TARGET_NODES
  export BK_ESTIMATION_FUTURE_TARGET_NODES
}

bk_estimation_load_package() {
  local package_name="$1"

  source "scripts/estimation/packages/${package_name}.sh"
  BK_ESTIMATION_PACKAGE_VERSION=$(bk_estimation_package_metadata | jq -r '.version // empty')
  BK_ESTIMATION_MODEL_VERSION="${BK_ESTIMATION_MODEL_VERSION:-${BK_ESTIMATION_PACKAGE_VERSION:-0.1}}"
}

bk_estimation_build_model_json_from_metadata() {
  local role="$1"
  local source_system="$2"
  local target_system="$3"
  local default_type="$4"
  local default_name="$5"
  local default_rule="$6"
  local model_version="${7:-${BK_ESTIMATION_PACKAGE_VERSION:-0.1}}"
  local package_metadata
  local role_metadata

  package_metadata=$(bk_estimation_package_metadata)
  role_metadata=$(echo "$package_metadata" | jq -c --arg role "$role" '.models[$role] // {}')

  jq -cn \
    --arg type "$(echo "$role_metadata" | jq -r --arg v "$default_type" '.type // $v')" \
    --arg name "$(echo "$role_metadata" | jq -r --arg v "$default_name" '.name // $v')" \
    --arg version "$model_version" \
    --arg source_system "$source_system" \
    --arg target_system "$target_system" \
    --arg system_compatibility_rule "$(echo "$role_metadata" | jq -r --arg v "$default_rule" '.system_compatibility_rule // $v')" \
    --arg implementation "scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh" \
    --arg role "$role" '
    {
      type: $type,
      name: $name,
      version: $version
    }
    + (if $source_system != "" then {source_system: $source_system} else {} end)
    + (if $target_system != "" then {target_system: $target_system} else {} end)
    + (if $system_compatibility_rule != "" then {system_compatibility_rule: $system_compatibility_rule} else {} end)
    + (if $role == "top_level" then {implementation: $implementation} else {} end)
  '
}

bk_estimation_model_name_from_metadata() {
  local role="$1"
  local default_name="$2"

  bk_estimation_package_metadata | jq -r --arg role "$role" --arg v "$default_name" '.models[$role].name // $v'
}

bk_estimation_apply_package_metadata_from_definition() {
  local package_name="$1"
  local package_metadata
  local package_version
  local method_class
  local detail_level

  package_metadata=$(bk_estimation_package_metadata)
  package_version=$(echo "$package_metadata" | jq -r '.version // "0.1"')
  method_class=$(echo "$package_metadata" | jq -r '.method_class // ""')
  detail_level=$(echo "$package_metadata" | jq -r '.detail_level // ""')

  bk_estimation_set_package_metadata \
    "$package_name" \
    "$package_version" \
    "$method_class" \
    "$detail_level"
}

bk_estimation_apply_package_output_defaults_from_metadata() {
  local package_metadata

  package_metadata=$(bk_estimation_package_metadata)

  if [[ -z "$est_measurement_json" || "$est_measurement_json" == "null" ]]; then
    est_measurement_json=$(echo "$package_metadata" | jq -c '.defaults.measurement // empty')
  fi
  if [[ -z "$est_confidence_json" || "$est_confidence_json" == "null" ]]; then
    est_confidence_json=$(echo "$package_metadata" | jq -c '.defaults.confidence // empty')
  fi
  if [[ -z "$est_notes_json" || "$est_notes_json" == "null" ]]; then
    est_notes_json=$(echo "$package_metadata" | jq -c '.defaults.notes // empty')
  fi
}

bk_estimation_build_assumptions_json_from_metadata() {
  local baseline_system="$1"
  local future_system="$2"
  local current_target_nodes="$3"
  local future_target_nodes="$4"
  local logp_package_name="${5:-logp}"
  local logp_section_name="${6:-}"
  local package_metadata
  local assumption_defaults

  package_metadata=$(bk_estimation_package_metadata)
  assumption_defaults=$(echo "$package_metadata" | jq -c '.defaults.assumptions // {}')

  jq -cn \
    --arg baseline_system "$baseline_system" \
    --arg future_system "$future_system" \
    --arg current_target_nodes "$current_target_nodes" \
    --arg future_target_nodes "$future_target_nodes" \
    --arg logp_package_name "$logp_package_name" \
    --arg logp_section_name "$logp_section_name" \
    --argjson defaults "$assumption_defaults" '
    {}
    + (if ($defaults.scaling_assumption // "") != "" then {scaling_assumption: $defaults.scaling_assumption} else {} end)
    + (if $baseline_system != "" then {baseline_system: $baseline_system} else {} end)
    + (if $future_system != "" then {future_system_assumption: $future_system} else {} end)
    + (if $current_target_nodes != "" then {current_target_nodes: $current_target_nodes} else {} end)
    + (if $future_target_nodes != "" then {future_target_nodes: $future_target_nodes} else {} end)
    + (if ($defaults.default_section_rule // "") != "" then {default_section_rule: $defaults.default_section_rule} else {} end)
    + (if ($defaults.logp_section_rule_template // "") != "" then {logp_section_rule: ($defaults.logp_section_rule_template | gsub("\\{logp_package_name\\}"; $logp_package_name))} else {} end)
    + (if ($defaults.logp_reference_section // "") != "" or $logp_section_name != "" then {logp_reference_section: (if $logp_section_name != "" then $logp_section_name else $defaults.logp_reference_section end)} else {} end)
    + (if ($defaults.overlap_rule // "") != "" then {overlap_rule: $defaults.overlap_rule} else {} end)
  '
}

bk_estimation_run_recorded_current_with_weakscaling() {
  local baseline_system="${1:-${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}}"
  local baseline_exp="${2:-${BK_ESTIMATION_BASELINE_EXP:-CASE0}}"
  local current_target_nodes="${3:-${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}}"
  local current_package="${4:-${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}}"
  local current_model_version=""
  local baseline_breakdown=""

  bk_estimation_load_package "$current_package"
  current_model_version="${BK_ESTIMATION_PACKAGE_VERSION:-0.1}"

  fetch_current_fom "$baseline_system" "$est_code" "$baseline_exp"
  baseline_breakdown="$est_current_fom_breakdown"
  if [[ -z "$baseline_breakdown" || "$baseline_breakdown" == "null" ]]; then
    baseline_breakdown="$est_input_fom_breakdown"
  fi

  est_current_system="$baseline_system"
  est_current_target_nodes="$current_target_nodes"
  est_current_scaling_method="$current_package"
  est_current_fom_breakdown=$(bk_top_level_transform_breakdown \
    "$baseline_breakdown" \
    "$current_target_nodes" \
    "${est_current_bench_nodes:-1}" \
    "1" \
    "identity" \
    "identity")
  est_current_fom=$(bk_top_level_breakdown_total_time "$est_current_fom_breakdown")
  if declare -F bk_estimation_package_build_recorded_current_model_json >/dev/null 2>&1; then
    est_current_model_json=$(bk_estimation_package_build_recorded_current_model_json "$baseline_system" "$current_model_version")
  else
    est_current_model_json=$(bk_estimation_build_model_json_from_metadata \
      "recorded_current" \
      "$baseline_system" \
      "$baseline_system" \
      "intra_system_scaling_model" \
      "${current_package}-current" \
      "same_system_line" \
      "$current_model_version")
  fi

  bk_estimation_set_current_package_metadata \
    "$current_package" \
    "$current_model_version" \
    "$current_package" \
    "$current_model_version"
}

bk_estimation_run_declared_future_package() {
  local input_json="$1"
  local future_package="${BK_ESTIMATION_FUTURE_PACKAGE:-}"

  if [[ -z "$future_package" ]]; then
    echo "ERROR: BK_ESTIMATION_FUTURE_PACKAGE is not set" >&2
    return 1
  fi

  read_values "$input_json"

  BK_ESTIMATION_PACKAGE="$future_package"
  unset BK_ESTIMATION_MODEL_NAME || true
  unset BK_ESTIMATION_MODEL_VERSION || true

  if ! bk_estimation_execute_with_fallback bk_estimation_load_package; then
    echo "ERROR: estimation package ${future_package} is not applicable for input ${input_json}" >&2
    return 1
  fi

  return 0
}

bk_estimation_write_output() {
  local output_file="$1"

  mkdir -p "$(dirname "$output_file")"
  print_json > "$output_file"
  echo "Estimate written to $output_file"
}

# ---------------------------------------------------------------------------
# read_values — Read benchmark Result_JSON into global variables
#
# Arguments:
#   $1  Path to a Result_JSON file
#
# Sets: est_code, est_exp, est_fom, est_system, est_node_count
# Exits with 1 on missing file or missing FOM field.
# ---------------------------------------------------------------------------
read_values() {
  local json_file="$1"

  if [[ ! -f "$json_file" ]]; then
    echo "ERROR: File not found: $json_file" >&2
    exit 1
  fi

  est_code=$(jq -r '.code' "$json_file")
  est_exp=$(jq -r '.Exp' "$json_file")
  est_system=$(jq -r '.system' "$json_file")
  est_node_count=$(jq -r '.node_count' "$json_file")
  est_numproc_node=$(jq -r '.numproc_node // empty' "$json_file")

  # Read server-assigned uuid and timestamp (written back by send_results.sh)
  est_uuid=$(jq -r '._server_uuid // empty' "$json_file")
  est_timestamp=$(jq -r '._server_timestamp // empty' "$json_file")
  est_timestamp=$(_bk_normalize_estimation_timestamp "$est_timestamp")

  # Fallback: read send_results manifest if the result JSON itself does not
  # carry the server-assigned metadata.
  if [[ -z "$est_uuid" || -z "$est_timestamp" ]]; then
    local meta_file
    local basename
    meta_file="$(dirname "$json_file")/server_result_meta.json"
    basename=$(basename "$json_file")
    if [[ -f "$meta_file" ]]; then
      if [[ -z "$est_uuid" ]]; then
        est_uuid=$(jq -r --arg file "$basename" '.[$file].uuid // empty' "$meta_file")
      fi
      if [[ -z "$est_timestamp" ]]; then
        est_timestamp=$(jq -r --arg file "$basename" '.[$file].timestamp // empty' "$meta_file")
        est_timestamp=$(_bk_normalize_estimation_timestamp "$est_timestamp")
      fi
    fi
  fi

  # Fallback: extract from filename if not in JSON
  if [[ -z "$est_uuid" || -z "$est_timestamp" ]]; then
    local basename
    basename=$(basename "$json_file")
    if [[ -z "$est_timestamp" ]]; then
      local ts_match
      ts_match=$(echo "$basename" | grep -Eo '[0-9]{8}_[0-9]{6}' | head -n1 || true)
      if [[ -n "$ts_match" ]]; then
        est_timestamp="${ts_match:0:4}-${ts_match:4:2}-${ts_match:6:2} ${ts_match:9:2}:${ts_match:11:2}:${ts_match:13:2}"
      fi
    fi
    if [[ -z "$est_uuid" ]]; then
      local uuid_match
      uuid_match=$(echo "$basename" | grep -Eoi '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -n1 || true)
      est_uuid="${uuid_match:-}"
    fi
  fi

  # FOM field is required
  local fom_raw
  fom_raw=$(jq -r '.FOM // empty' "$json_file")
  if [[ -z "$fom_raw" ]]; then
    echo "ERROR: FOM field is missing in $json_file" >&2
    exit 1
  fi
  est_fom="$fom_raw"
  est_input_fom_breakdown=$(jq -c '.fom_breakdown // empty' "$json_file")

  # By default, keep the input benchmark result UUID as the source UUID
  # for the estimation result. Package-aware estimation scripts may override
  # this explicitly when needed.
  est_source_result_uuid="$est_uuid"

  load_reestimation_context
}

# ---------------------------------------------------------------------------
# performance_ratio — Compute current_fom / future_fom
#
# Uses global variables est_current_fom and est_future_fom.
# Outputs 0 when est_future_fom is 0 (avoids division by zero).
# ---------------------------------------------------------------------------
performance_ratio() {
  awk -v cur="$est_current_fom" -v fut="$est_future_fom" '
    BEGIN {
      if (cur == "" || cur == "null" || fut == "" || fut == "null") {
        printf "null"
      } else if (fut == 0) {
        printf "0"
      } else {
        printf "%.3f", cur / fut
      }
    }'
}

# ---------------------------------------------------------------------------
# bk_estimation_set_package_metadata — Set package-oriented metadata fields
#
# Arguments:
#   $1  estimation package name
#   $2  estimation package version
#   $3  method_class
#   $4  detail_level
# ---------------------------------------------------------------------------
bk_estimation_set_package_metadata() {
  est_estimation_package="${1:-}"
  est_estimation_package_version="${2:-}"
  est_method_class="${3:-}"
  est_detail_level="${4:-}"
}

bk_estimation_set_current_package_metadata() {
  est_current_estimation_package="${1:-}"
  est_current_estimation_package_version="${2:-}"
  est_requested_current_estimation_package="${3:-${1:-}}"
  est_requested_current_estimation_package_version="${4:-${2:-}}"
}

bk_estimation_set_future_package_metadata() {
  est_future_estimation_package="${1:-}"
  est_future_estimation_package_version="${2:-}"
  est_requested_future_estimation_package="${3:-${1:-}}"
  est_requested_future_estimation_package_version="${4:-${2:-}}"
}

bk_estimation_finalize_side_package_metadata() {
  if [[ -z "$est_current_estimation_package" ]]; then
    est_current_estimation_package="$est_estimation_package"
  fi
  if [[ -z "$est_current_estimation_package_version" ]]; then
    est_current_estimation_package_version="$est_estimation_package_version"
  fi
  if [[ -z "$est_requested_current_estimation_package" ]]; then
    est_requested_current_estimation_package="$est_requested_estimation_package"
  fi
  if [[ -z "$est_requested_current_estimation_package_version" ]]; then
    est_requested_current_estimation_package_version="$est_requested_estimation_package_version"
  fi

  if [[ -z "$est_future_estimation_package" ]]; then
    est_future_estimation_package="$est_estimation_package"
  fi
  if [[ -z "$est_future_estimation_package_version" ]]; then
    est_future_estimation_package_version="$est_estimation_package_version"
  fi
  if [[ -z "$est_requested_future_estimation_package" ]]; then
    est_requested_future_estimation_package="$est_requested_estimation_package"
  fi
  if [[ -z "$est_requested_future_estimation_package_version" ]]; then
    est_requested_future_estimation_package_version="$est_requested_estimation_package_version"
  fi
}

bk_estimation_reset_output_state() {
  est_current_system=""
  est_current_fom=""
  est_current_target_nodes=""
  est_current_scaling_method=""
  est_future_system=""
  est_future_fom=""
  est_future_target_nodes=""
  est_future_scaling_method=""
  est_current_model_json=""
  est_future_model_json=""
  est_current_fom_breakdown=""
  est_future_fom_breakdown=""
  est_current_estimation_package=""
  est_current_estimation_package_version=""
  est_requested_current_estimation_package=""
  est_requested_current_estimation_package_version=""
  est_future_estimation_package=""
  est_future_estimation_package_version=""
  est_requested_future_estimation_package=""
  est_requested_future_estimation_package_version=""
  est_measurement_json=""
  est_assumptions_json=""
  est_input_artifacts_json=""
  est_model_json=""
  est_confidence_json=""
  est_notes_json=""
  est_reestimation_json=""
}

# ---------------------------------------------------------------------------
# bk_estimation_set_applicability — Build applicability JSON for Estimate JSON
#
# Arguments:
#   $1  status
#   $2  fallback_used         (optional)
#   $3  missing_inputs_json   (optional, JSON array)
#   $4  required_actions_json (optional, JSON array)
#   $5  incompatibilities_json (optional, JSON array)
# ---------------------------------------------------------------------------
bk_estimation_set_applicability() {
  local status="${1:-}"
  local fallback_used="${2:-}"
  local missing_inputs_json="${3:-[]}"
  local required_actions_json="${4:-[]}"
  local incompatibilities_json="${5:-[]}"

  est_applicability_json=$(jq -cn \
    --arg status "$status" \
    --arg fallback_used "$fallback_used" \
    --argjson missing_inputs "$missing_inputs_json" \
    --argjson required_actions "$required_actions_json" \
    --argjson incompatibilities "$incompatibilities_json" \
    '{
      status: $status
    }
    + (if $fallback_used != "" then {fallback_used: $fallback_used} else {} end)
    + (if ($missing_inputs | length) > 0 then {missing_inputs: $missing_inputs} else {} end)
    + (if ($required_actions | length) > 0 then {required_actions: $required_actions} else {} end)
    + (if ($incompatibilities | length) > 0 then {incompatibilities: $incompatibilities} else {} end)')
}

_bk_system_line() {
  local system_name="${1:-}"

  case "$system_name" in
    Fugaku|FugakuCN|FugakuLN)
      echo "Fugaku"
      ;;
    MiyabiG|MiyabiC)
      echo "Miyabi"
      ;;
    *)
      echo "$system_name"
      ;;
  esac
}

bk_estimation_validate_system_relation() {
  local model_kind="${1:-}"
  local source_system="${2:-}"
  local target_system="${3:-}"
  local compatibility_rule="${4:-exact_match}"

  if [[ -z "$model_kind" || -z "$source_system" || -z "$target_system" ]]; then
    return 1
  fi

  case "$model_kind" in
    intra_system_scaling_model)
      case "$compatibility_rule" in
        exact_match)
          [[ "$source_system" == "$target_system" ]]
          ;;
        same_system_line)
          [[ "$(_bk_system_line "$source_system")" == "$(_bk_system_line "$target_system")" ]]
          ;;
        *)
          return 1
          ;;
      esac
      ;;
    cross_system_projection_model)
      case "$compatibility_rule" in
        cross_system_allowed|same_system_line|exact_match)
          return 0
          ;;
        *)
          return 1
          ;;
      esac
      ;;
    *)
      return 1
      ;;
  esac
}

bk_estimation_execute_with_fallback() {
  local loader_function="$1"

  est_requested_estimation_package="${BK_ESTIMATION_PACKAGE:-}"
  est_requested_estimation_package_version="${BK_ESTIMATION_PACKAGE_VERSION:-}"
  "$loader_function" "$BK_ESTIMATION_PACKAGE"

  if ! bk_estimation_package_check_applicability; then
    local fallback_package
    local fallback_status
    fallback_package=$(jq -r '.fallback_used // empty' <<< "${est_applicability_json:-null}")
    fallback_status=$(jq -r '.status // empty' <<< "${est_applicability_json:-null}")

    if [[ "$fallback_status" == "fallback" && -n "$fallback_package" ]]; then
      echo "Falling back from ${BK_ESTIMATION_PACKAGE} to ${fallback_package}"
      BK_ESTIMATION_PACKAGE="$fallback_package"
      bk_estimation_reset_output_state
      "$loader_function" "$BK_ESTIMATION_PACKAGE"
      bk_estimation_package_run
      bk_estimation_package_apply_metadata
      return 0
    fi

    return 1
  fi

  bk_estimation_package_run
  bk_estimation_package_apply_metadata
  return 0
}

# ---------------------------------------------------------------------------
# fetch_current_fom — Fetch baseline-system FOM from result_server API
#
# Arguments:
#   $1  system (e.g. Fugaku)
#   $2  code   (e.g. qws)
#   $3  exp    (optional, e.g. default)
#
# Requires: RESULT_SERVER, RESULT_SERVER_KEY environment variables
# Sets: est_current_fom (FOM value from the selected baseline-system result)
# Exits with 1 on failure.
# ---------------------------------------------------------------------------
fetch_current_fom() {
  local system="$1"
  local code="$2"
  local exp="${3:-}"

  local url="${RESULT_SERVER}/api/query/result?system=${system}&code=${code}"
  if [[ -n "$exp" ]]; then
    url="${url}&exp=${exp}"
  fi

  local response
  local curl_exit
  set +e
  response=$(bk_result_server_get_json "/api/query/result?system=${system}&code=${code}${exp:+&exp=${exp}}")
  curl_exit=$?
  set -e
  if [[ $curl_exit -ne 0 || -z "$response" ]]; then
    echo "ERROR: Failed to fetch baseline result for system=${system}, code=${code}, exp=${exp} (curl exit=$curl_exit)" >&2
    echo "ERROR: URL was: ${url}" >&2
    exit 1
  fi

  est_current_fom=$(echo "$response" | jq -r '.FOM')
  if [[ -z "$est_current_fom" || "$est_current_fom" == "null" ]]; then
    echo "ERROR: FOM not found in baseline result for system=${system}, code=${code}, exp=${exp}" >&2
    exit 1
  fi

  # Populate benchmark sub-object variables for current_system
  est_current_bench_system="$system"
  est_current_bench_fom="$est_current_fom"
  est_current_bench_nodes=$(echo "$response" | jq -r '.node_count // empty')
  est_current_bench_numproc_node=$(echo "$response" | jq -r '.numproc_node // empty')
  est_current_bench_timestamp=$(echo "$response" | jq -r '._meta.timestamp // empty')
  est_current_bench_uuid=$(echo "$response" | jq -r '._meta.uuid // empty')
  est_current_fom_breakdown=$(echo "$response" | jq -c '.fom_breakdown // empty')

  echo "Fetched baseline FOM for ${system}/${code}: ${est_current_fom}"
}

# ---------------------------------------------------------------------------
# print_json — Output an Estimate_JSON to stdout
#
# Reads all est_* global variables and produces a JSON document compatible
# with result_server's load_estimated_results_table / ESTIMATED_FIELD_MAP.
# ---------------------------------------------------------------------------
print_json() {
  bk_estimation_finalize_side_package_metadata
  local ratio
  ratio=$(performance_ratio)
  local current_fom_value="${est_current_fom:-null}"
  local future_fom_value="${est_future_fom:-null}"

  # Build fom_breakdown blocks conditionally
  local current_breakdown_block=""
  if [[ -n "$est_current_fom_breakdown" && "$est_current_fom_breakdown" != "null" ]]; then
    current_breakdown_block=",
      \"fom_breakdown\": $est_current_fom_breakdown"
  fi
  local future_breakdown_block=""
  if [[ -n "$est_future_fom_breakdown" && "$est_future_fom_breakdown" != "null" ]]; then
    future_breakdown_block=",
      \"fom_breakdown\": $est_future_fom_breakdown"
  fi
  local current_model_block=""
  if [[ -n "$est_current_model_json" && "$est_current_model_json" != "null" ]]; then
    current_model_block=",
      \"model\": $est_current_model_json"
  fi
  local future_model_block=""
  if [[ -n "$est_future_model_json" && "$est_future_model_json" != "null" ]]; then
    future_model_block=",
      \"model\": $est_future_model_json"
  fi

  local estimate_metadata_block=""
  if [[ -n "$est_estimation_id" || -n "$est_estimation_timestamp" || -n "$est_method_class" || -n "$est_detail_level" || -n "$est_source_result_uuid" || -n "$est_estimation_package" || -n "$est_estimation_package_version" || -n "$est_requested_estimation_package" || -n "$est_requested_estimation_package_version" || -n "$est_current_estimation_package" || -n "$est_requested_current_estimation_package" || -n "$est_future_estimation_package" || -n "$est_requested_future_estimation_package" ]]; then
    local estimate_metadata_json=""
    estimate_metadata_json=$(jq -cn \
      --arg estimation_id "$est_estimation_id" \
      --arg timestamp "$est_estimation_timestamp" \
      --arg method_class "$est_method_class" \
      --arg detail_level "$est_detail_level" \
      --arg source_result_uuid "$est_source_result_uuid" \
      --arg estimation_package "$est_estimation_package" \
      --arg estimation_package_version "$est_estimation_package_version" \
      --arg requested_estimation_package "$est_requested_estimation_package" \
      --arg requested_estimation_package_version "$est_requested_estimation_package_version" \
      --arg current_estimation_package "$est_current_estimation_package" \
      --arg current_estimation_package_version "$est_current_estimation_package_version" \
      --arg requested_current_estimation_package "$est_requested_current_estimation_package" \
      --arg requested_current_estimation_package_version "$est_requested_current_estimation_package_version" \
      --arg future_estimation_package "$est_future_estimation_package" \
      --arg future_estimation_package_version "$est_future_estimation_package_version" \
      --arg requested_future_estimation_package "$est_requested_future_estimation_package" \
      --arg requested_future_estimation_package_version "$est_requested_future_estimation_package_version" \
      '{} 
      + (if $estimation_id != "" then {estimation_id: $estimation_id} else {} end)
      + (if $timestamp != "" then {timestamp: $timestamp} else {} end)
      + (if $method_class != "" then {method_class: $method_class} else {} end)
      + (if $detail_level != "" then {detail_level: $detail_level} else {} end)
      + (if $source_result_uuid != "" then {source_result_uuid: $source_result_uuid} else {} end)
      + (if $estimation_package != "" then {estimation_package: $estimation_package} else {} end)
      + (if $estimation_package_version != "" then {estimation_package_version: $estimation_package_version} else {} end)
      + (if $requested_estimation_package != "" then {requested_estimation_package: $requested_estimation_package} else {} end)
      + (if $requested_estimation_package_version != "" then {requested_estimation_package_version: $requested_estimation_package_version} else {} end)
      + (if $current_estimation_package != "" or $requested_current_estimation_package != "" then {
          current_package:
            ((if $current_estimation_package != "" then {estimation_package: $current_estimation_package} else {} end)
            + (if $current_estimation_package_version != "" then {estimation_package_version: $current_estimation_package_version} else {} end)
            + (if $requested_current_estimation_package != "" then {requested_estimation_package: $requested_current_estimation_package} else {} end)
            + (if $requested_current_estimation_package_version != "" then {requested_estimation_package_version: $requested_current_estimation_package_version} else {} end))
        } else {} end)
      + (if $future_estimation_package != "" or $requested_future_estimation_package != "" then {
          future_package:
            ((if $future_estimation_package != "" then {estimation_package: $future_estimation_package} else {} end)
            + (if $future_estimation_package_version != "" then {estimation_package_version: $future_estimation_package_version} else {} end)
            + (if $requested_future_estimation_package != "" then {requested_estimation_package: $requested_future_estimation_package} else {} end)
            + (if $requested_future_estimation_package_version != "" then {requested_estimation_package_version: $requested_future_estimation_package_version} else {} end))
        } else {} end)')
    estimate_metadata_block=",
  \"estimate_metadata\": $estimate_metadata_json"
  fi

  local measurement_block=""
  if [[ -n "$est_measurement_json" && "$est_measurement_json" != "null" ]]; then
    measurement_block=",
  \"measurement\": $est_measurement_json"
  fi

  local assumptions_block=""
  if [[ -n "$est_assumptions_json" && "$est_assumptions_json" != "null" ]]; then
    assumptions_block=",
  \"assumptions\": $est_assumptions_json"
  fi

  local input_artifacts_block=""
  if [[ -n "$est_input_artifacts_json" && "$est_input_artifacts_json" != "null" ]]; then
    input_artifacts_block=",
  \"input_artifacts\": $est_input_artifacts_json"
  fi

  local model_block=""
  if [[ -n "$est_model_json" && "$est_model_json" != "null" ]]; then
    model_block=",
  \"model\": $est_model_json"
  fi

  local applicability_block=""
  if [[ -n "$est_applicability_json" && "$est_applicability_json" != "null" ]]; then
    applicability_block=",
  \"applicability\": $est_applicability_json"
  fi

  local confidence_block=""
  if [[ -n "$est_confidence_json" && "$est_confidence_json" != "null" ]]; then
    confidence_block=",
  \"confidence\": $est_confidence_json"
  fi

  local notes_block=""
  if [[ -n "$est_notes_json" && "$est_notes_json" != "null" ]]; then
    notes_block=",
  \"notes\": $est_notes_json"
  fi

  local reestimation_block=""
  if [[ -n "$est_reestimation_json" && "$est_reestimation_json" != "null" ]]; then
    reestimation_block=",
  \"reestimation\": $est_reestimation_json"
  fi

  cat <<EOF
{
  "code": "$est_code",
  "exp": "$est_exp",
  "current_system": {
    "system": "$est_current_system",
    "fom": $current_fom_value,
    "target_nodes": "$est_current_target_nodes",
    "scaling_method": "$est_current_scaling_method",
    "benchmark": {
      "system": "$est_current_bench_system",
      "fom": $est_current_bench_fom,
      "nodes": "$est_current_bench_nodes",
      "numproc_node": "$est_current_bench_numproc_node",
      "timestamp": "$est_current_bench_timestamp",
      "uuid": "$est_current_bench_uuid"
    }${current_breakdown_block}${current_model_block}
  },
  "future_system": {
    "system": "$est_future_system",
    "fom": $future_fom_value,
    "target_nodes": "$est_future_target_nodes",
    "scaling_method": "$est_future_scaling_method",
    "benchmark": {
      "system": "$est_future_bench_system",
      "fom": $est_future_bench_fom,
      "nodes": "$est_future_bench_nodes",
      "numproc_node": "$est_future_bench_numproc_node",
      "timestamp": "$est_future_bench_timestamp",
      "uuid": "$est_future_bench_uuid"
    }${future_breakdown_block}${future_model_block}
  },
  "performance_ratio": $ratio${estimate_metadata_block}${measurement_block}${assumptions_block}${input_artifacts_block}${model_block}${applicability_block}${confidence_block}${notes_block}${reestimation_block}
}
EOF
}

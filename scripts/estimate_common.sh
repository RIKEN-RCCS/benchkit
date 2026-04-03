#!/bin/bash
# estimate_common.sh — Common function library for performance estimation
#
# Provides shared variables and functions used by application-specific
# estimate scripts (programs/<code>/estimate.sh).
#
# Usage:
#   source scripts/estimate_common.sh

set -euo pipefail

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

# fom_breakdown JSON strings (optional, set by estimate scripts)
est_current_fom_breakdown=""
est_future_fom_breakdown=""

# Optional top-level metadata blocks for extended Estimate JSON
est_estimation_id=""
est_estimation_timestamp=""
est_method_class=""
est_detail_level=""
est_measurement_json=""
est_assumptions_json=""
est_input_artifacts_json=""
est_model_json=""
est_confidence_json=""
est_notes_json=""

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
}

# ---------------------------------------------------------------------------
# performance_ratio — Compute current_fom / future_fom
#
# Uses global variables est_current_fom and est_future_fom.
# Outputs 0 when est_future_fom is 0 (avoids division by zero).
# ---------------------------------------------------------------------------
performance_ratio() {
  awk -v cur="$est_current_fom" -v fut="$est_future_fom" \
    'BEGIN { if (fut == 0) printf "0"; else printf "%.3f", cur / fut }'
}

# ---------------------------------------------------------------------------
# fetch_current_fom — Fetch Fugaku FOM from result_server API
#
# Arguments:
#   $1  code (e.g. qws)
#   $2  exp  (optional, e.g. default)
#
# Requires: RESULT_SERVER, RESULT_SERVER_KEY environment variables
# Sets: est_current_fom (FOM value from Fugaku result)
# Exits with 1 on failure.
# ---------------------------------------------------------------------------
fetch_current_fom() {
  local code="$1"
  local exp="${2:-}"

  if [[ -z "${RESULT_SERVER:-}" ]]; then
    echo "ERROR: RESULT_SERVER is not set" >&2
    exit 1
  fi
  if [[ -z "${RESULT_SERVER_KEY:-}" ]]; then
    echo "ERROR: RESULT_SERVER_KEY is not set" >&2
    exit 1
  fi

  local url="${RESULT_SERVER}/api/query/result?system=Fugaku&code=${code}"
  if [[ -n "$exp" ]]; then
    url="${url}&exp=${exp}"
  fi

  local response
  local curl_exit
  set +e
  response=$(curl -sf -H "X-API-Key: ${RESULT_SERVER_KEY}" "$url")
  curl_exit=$?
  set -e
  if [[ $curl_exit -ne 0 || -z "$response" ]]; then
    echo "ERROR: Failed to fetch Fugaku result for code=${code}, exp=${exp} (curl exit=$curl_exit)" >&2
    echo "ERROR: URL was: ${url}" >&2
    exit 1
  fi

  est_current_fom=$(echo "$response" | jq -r '.FOM')
  if [[ -z "$est_current_fom" || "$est_current_fom" == "null" ]]; then
    echo "ERROR: FOM not found in Fugaku result for code=${code}, exp=${exp}" >&2
    exit 1
  fi

  # Populate benchmark sub-object variables for current_system
  est_current_bench_system="Fugaku"
  est_current_bench_fom="$est_current_fom"
  est_current_bench_nodes=$(echo "$response" | jq -r '.node_count // empty')
  est_current_bench_numproc_node=$(echo "$response" | jq -r '.numproc_node // empty')
  est_current_bench_timestamp=$(echo "$response" | jq -r '._meta.timestamp // empty')
  est_current_bench_uuid=$(echo "$response" | jq -r '._meta.uuid // empty')

  echo "Fetched Fugaku FOM for ${code}: ${est_current_fom}"
}

# ---------------------------------------------------------------------------
# print_json — Output an Estimate_JSON to stdout
#
# Reads all est_* global variables and produces a JSON document compatible
# with result_server's load_estimated_results_table / ESTIMATED_FIELD_MAP.
# ---------------------------------------------------------------------------
print_json() {
  local ratio
  ratio=$(performance_ratio)

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

  local estimate_metadata_block=""
  if [[ -n "$est_estimation_id" || -n "$est_estimation_timestamp" || -n "$est_method_class" || -n "$est_detail_level" ]]; then
    estimate_metadata_block=",
  \"estimate_metadata\": {
    \"estimation_id\": \"${est_estimation_id}\",
    \"timestamp\": \"${est_estimation_timestamp}\",
    \"method_class\": \"${est_method_class}\",
    \"detail_level\": \"${est_detail_level}\"
  }"
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

  cat <<EOF
{
  "code": "$est_code",
  "exp": "$est_exp",
  "current_system": {
    "system": "$est_current_system",
    "fom": $est_current_fom,
    "target_nodes": "$est_current_target_nodes",
    "scaling_method": "$est_current_scaling_method",
    "benchmark": {
      "system": "$est_current_bench_system",
      "fom": $est_current_bench_fom,
      "nodes": "$est_current_bench_nodes",
      "numproc_node": "$est_current_bench_numproc_node",
      "timestamp": "$est_current_bench_timestamp",
      "uuid": "$est_current_bench_uuid"
    }${current_breakdown_block}
  },
  "future_system": {
    "system": "$est_future_system",
    "fom": $est_future_fom,
    "target_nodes": "$est_future_target_nodes",
    "scaling_method": "$est_future_scaling_method",
    "benchmark": {
      "system": "$est_future_bench_system",
      "fom": $est_future_bench_fom,
      "nodes": "$est_future_bench_nodes",
      "numproc_node": "$est_future_bench_numproc_node",
      "timestamp": "$est_future_bench_timestamp",
      "uuid": "$est_future_bench_uuid"
    }${future_breakdown_block}
  },
  "performance_ratio": $ratio${estimate_metadata_block}${measurement_block}${assumptions_block}${input_artifacts_block}${model_block}${confidence_block}${notes_block}
}
EOF
}

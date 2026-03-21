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

# ---------------------------------------------------------------------------
# Global variables — set by application-specific estimate scripts,
# consumed by print_json
# ---------------------------------------------------------------------------
est_benchmark_system=""
est_benchmark_fom=""
est_benchmark_nodes=""
est_current_system=""
est_current_fom=""
est_current_nodes=""
est_current_method=""
est_future_system=""
est_future_fom=""
est_future_nodes=""
est_future_method=""

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
# print_json — Output an Estimate_JSON to stdout
#
# Reads all est_* global variables and produces a JSON document compatible
# with result_server's load_estimated_results_table / ESTIMATED_FIELD_MAP.
# ---------------------------------------------------------------------------
print_json() {
  local ratio
  ratio=$(performance_ratio)

  cat <<EOF
{
  "code": "$est_code",
  "exp": "$est_exp",
  "benchmark_system": "$est_benchmark_system",
  "benchmark_fom": $est_benchmark_fom,
  "benchmark_nodes": "$est_benchmark_nodes",
  "current_system": {
    "system": "$est_current_system",
    "fom": $est_current_fom,
    "nodes": "$est_current_nodes",
    "method": "$est_current_method"
  },
  "future_system": {
    "system": "$est_future_system",
    "fom": $est_future_fom,
    "nodes": "$est_future_nodes",
    "method": "$est_future_method"
  },
  "performance_ratio": $ratio
}
EOF
}

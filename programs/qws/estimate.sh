#!/bin/bash
# estimate.sh — Dummy estimation script for qws application
#
# Usage: bash programs/qws/estimate.sh <result_json_path>
# Output: results/estimate_<code>_0.json
#
# This script uses a simple scale-mock model for integration testing.
# Replace the estimation logic section below with a real estimation tool
# when available.

source scripts/estimate_common.sh

# --- Read benchmark result ---
read_values "$1"

# --- Future system benchmark: pass through from the benchmark run ---
est_future_bench_system="$est_system"
est_future_bench_fom="$est_fom"
est_future_bench_nodes="$est_node_count"
est_future_bench_numproc_node="$est_numproc_node"
est_future_bench_timestamp="$est_timestamp"
est_future_bench_uuid="$est_uuid"

# --- Current system: Fugaku — fetch real FOM from result_server ---
est_current_system="Fugaku"
CURRENT_EXP=""  # Set specific Exp here if needed (e.g. "default")
fetch_current_fom "$est_code" "$CURRENT_EXP"
# fetch_current_fom sets est_current_bench_* variables automatically
est_current_target_nodes="$est_node_count"
est_current_scaling_method="measured"

# --- Future system: FugakuNEXT — FOM scaled by 2x (dummy) ---
est_future_system="FugakuNEXT"
est_future_fom=$(awk -v fom="$est_fom" 'BEGIN {printf "%.3f", fom * 2}')
est_future_target_nodes="$est_node_count"
est_future_scaling_method="scale-mock"

# --- fom_breakdown (pass through from benchmark result if available) ---
est_current_fom_breakdown=""  # Fugaku benchmark may not have fom_breakdown
est_future_fom_breakdown=$(jq -c '.fom_breakdown // empty' "$1")

# --- Output ---
mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"

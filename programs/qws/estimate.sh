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

# --- Benchmark values (pass through from the benchmark run) ---
est_benchmark_system="$est_system"
est_benchmark_fom="$est_fom"
est_benchmark_nodes="$est_node_count"

# --- Dummy estimation model (scale-mock) ---
# Current system: Fugaku — FOM scaled by 10x
est_current_system="Fugaku"
est_current_fom=$(awk -v fom="$est_fom" 'BEGIN {printf "%.3f", fom * 10}')
est_current_nodes="$est_node_count"
est_current_method="scale-mock"

# Future system: FugakuNEXT — FOM scaled by 2x
est_future_system="FugakuNEXT"
est_future_fom=$(awk -v fom="$est_fom" 'BEGIN {printf "%.3f", fom * 2}')
est_future_nodes="$est_node_count"
est_future_method="scale-mock"

# --- Output ---
mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"

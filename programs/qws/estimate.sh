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
CURRENT_EXP="CASE0"  # Use CASE0 for Fugaku baseline
fetch_current_fom "$est_code" "$CURRENT_EXP"
# fetch_current_fom sets est_current_bench_* variables automatically
est_current_target_nodes="$est_node_count"
est_current_scaling_method="measured"

# --- Future system: FugakuNEXT — FOM scaled by 2x (dummy) ---
est_future_system="FugakuNEXT"
est_future_fom=$(awk -v fom="$est_fom" 'BEGIN {printf "%.3f", fom * 2}')
est_future_target_nodes="$est_node_count"
est_future_scaling_method="scale-mock"

# --- fom_breakdown (extend with bench_time, scaling_method, time per section) ---
# Read raw fom_breakdown from benchmark result
raw_breakdown=$(jq -c '.fom_breakdown // empty' "$1")

if [[ -n "$raw_breakdown" ]]; then
  # Future system: scale each section/overlap time by 2x (dummy)
  est_future_fom_breakdown=$(echo "$raw_breakdown" | jq -c '{
    sections: [.sections[] | {name, bench_time: .time, scaling_method: "scale-mock", time: (.time * 2)}],
    overlaps: [.overlaps[] | {sections, bench_time: .time, scaling_method: "scale-mock", time: (.time * 2)}]
  }')

  # Current system: measured, so time == bench_time (no scaling)
  est_current_fom_breakdown=$(echo "$raw_breakdown" | jq -c '{
    sections: [.sections[] | {name, bench_time: .time, scaling_method: "measured", time: .time}],
    overlaps: [.overlaps[] | {sections, bench_time: .time, scaling_method: "measured", time: .time}]
  }')

  # Compute FOM from breakdown: Σsections.time - Σoverlaps.time
  est_future_fom=$(echo "$est_future_fom_breakdown" | jq '[.sections[].time] | add - ([.overlaps[].time] | add // 0)' | awk '{printf "%.3f", $1}')
  est_current_fom=$(echo "$est_current_fom_breakdown" | jq '[.sections[].time] | add - ([.overlaps[].time] | add // 0)' | awk '{printf "%.3f", $1}')
else
  est_future_fom_breakdown=""
  est_current_fom_breakdown=""
fi

# --- Output ---
mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"

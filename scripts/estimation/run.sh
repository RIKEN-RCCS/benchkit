#!/bin/bash
# run.sh — Estimation execution wrapper
#
# Called from CI job script section:
#   bash scripts/estimation/run.sh <code>
#
# Discovers result*.json files in results/ and runs the corresponding
# application-specific estimate script for each one.

set -euo pipefail

code="$1"
estimate_script="programs/${code}/estimate.sh"

# Check if the application has an estimate script
if [[ ! -f "$estimate_script" ]]; then
  echo "WARNING: $estimate_script not found, skipping estimation"
  exit 0
fi

# Run estimation for each result JSON
found=0
for json_file in results/result[0-9]*.json; do
  [[ ! -f "$json_file" ]] && continue
  found=1
  echo "Input result metadata for $json_file:"
  jq '{code, system, Exp, _server_uuid, _server_timestamp}' "$json_file" || true
  if [[ -f results/server_result_meta.json ]]; then
    echo "Available result metadata manifest:"
    jq . results/server_result_meta.json || true
  fi
  echo "Running estimation: $estimate_script $json_file"
  bash "$estimate_script" "$json_file"
done

if [[ "$found" -eq 0 ]]; then
  echo "WARNING: No result*.json found in results/, skipping estimation"
  exit 0
fi

# Confirm estimate output files
echo "Estimation complete. Estimate files:"
ls results/estimate*.json 2>/dev/null || echo "No estimate files generated"

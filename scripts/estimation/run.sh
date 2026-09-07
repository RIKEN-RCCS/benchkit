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

record_estimate_timing() {
  local elapsed_time="$1"
  shift

  local json_file
  for json_file in "$@"; do
    [[ -f "$json_file" ]] || continue
    local tmp_file="${json_file}.timing.$$"
    if ! jq --argjson elapsed_time "$elapsed_time" '
      .estimation_timing = ((.estimation_timing // {}) + {
        schema_version: 1,
        elapsed_time: $elapsed_time,
        unit: "s",
        recorded_by: "scripts/estimation/run.sh"
      })
    ' "$json_file" > "$tmp_file"; then
      rm -f "$tmp_file"
      return 1
    fi
    mv "$tmp_file" "$json_file"
  done
}

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
  marker_file=$(mktemp "${TMPDIR:-/tmp}/benchkit-estimate-marker.XXXXXX")
  estimate_start=$SECONDS
  bash "$estimate_script" "$json_file"
  estimate_elapsed=$((SECONDS - estimate_start))
  mapfile -t estimate_outputs < <(find results -maxdepth 1 -type f -name 'estimate*.json' -newer "$marker_file" | sort)
  rm -f "$marker_file"
  record_estimate_timing "$estimate_elapsed" "${estimate_outputs[@]}"
done

if [[ "$found" -eq 0 ]]; then
  echo "WARNING: No result*.json found in results/, skipping estimation"
  exit 0
fi

# Confirm estimate output files
echo "Estimation complete. Estimate files:"
ls results/estimate*.json 2>/dev/null || echo "No estimate files generated"

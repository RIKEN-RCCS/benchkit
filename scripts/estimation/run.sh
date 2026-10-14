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

expected_commit="${BK_ESTIMATION_EXPECTED_COMMIT:-}"
execution_commit=""
if [[ -n "$expected_commit" ]]; then
  if [[ ! "$expected_commit" =~ ^[[:xdigit:]]{40}$ ]]; then
    echo "ERROR: BK_ESTIMATION_EXPECTED_COMMIT must be a full commit SHA" >&2
    exit 1
  fi
  repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  execution_commit=$(git -C "$repo_dir" rev-parse --verify HEAD) || exit 1
  expected_commit="${expected_commit,,}"
  if [[ "$execution_commit" != "$expected_commit" ]]; then
    echo "ERROR: Estimation checkout does not match the requested commit" >&2
    exit 1
  fi
  if ! git -C "$repo_dir" diff --quiet HEAD --; then
    echo "ERROR: Estimation checkout has tracked changes" >&2
    exit 1
  fi
fi

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
    if ! jq --argjson elapsed_time "$elapsed_time" \
      --arg execution_commit "$execution_commit" '
      .estimation_timing = ((.estimation_timing // {}) + {
        schema_version: 1,
        elapsed_time: $elapsed_time,
        unit: "s",
        recorded_by: "scripts/estimation/run.sh"
      })
      | if $execution_commit != "" then
          .estimation_execution = ((.estimation_execution // {}) + {
            benchkit_commit: $execution_commit,
            requested_commit: $execution_commit
          })
        else . end
    ' "$json_file" > "$tmp_file"; then
      rm -f "$tmp_file"
      return 1
    fi
    mv "$tmp_file" "$json_file"
  done
}

# Both CI entry paths prepare inputs here before invoking any app estimator.
shopt -s nullglob
result_files=(results/result[0-9]*.json)
python3 "$(dirname "$0")/prepare_inputs.py" "${result_files[@]}"

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
  python3 "$(dirname "$0")/reestimation_conditions.py" "$estimate_script" "$json_file"
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

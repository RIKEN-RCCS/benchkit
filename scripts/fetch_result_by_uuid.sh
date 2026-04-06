#!/bin/bash
# Fetch a benchmark result JSON from the result server by UUID.
# Saves the result to results/result0.json for subsequent estimation.
#
# Required CI variables:
#   result_uuid          - UUID of the benchmark result to fetch directly
#   estimate_result_uuid - UUID of the estimate result to re-estimate from
#   estimate_uuid        - legacy alias for result_uuid
#   code           - Program code name (e.g., "qws")
#   RESULT_SERVER  - Base URL of the result server
set -euo pipefail

if [[ -z "${code:-}" ]]; then
  echo "ERROR: code must be specified" >&2
  exit 1
fi

mkdir -p results

resolved_result_uuid="${result_uuid:-}"

if [[ -z "$resolved_result_uuid" && -n "${estimate_result_uuid:-}" ]]; then
  echo "Fetching estimate for UUID: $estimate_result_uuid"
  curl --fail -sS -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    -o "results/source_estimate.json" \
    "${RESULT_SERVER}/api/query/estimate/${estimate_result_uuid}"

  resolved_result_uuid="$(jq -r '.estimate_metadata.source_result_uuid // empty' results/source_estimate.json)"
  if [[ -z "$resolved_result_uuid" ]]; then
    echo "ERROR: source_result_uuid not found in estimate ${estimate_result_uuid}" >&2
    exit 1
  fi
  echo "Resolved source result UUID: $resolved_result_uuid"
fi

if [[ -z "$resolved_result_uuid" && -n "${estimate_uuid:-}" ]]; then
  echo "WARNING: estimate_uuid is deprecated; use result_uuid or estimate_result_uuid" >&2
  resolved_result_uuid="$estimate_uuid"
fi

if [[ -z "$resolved_result_uuid" ]]; then
  echo "ERROR: one of result_uuid, estimate_result_uuid, or legacy estimate_uuid must be specified" >&2
  exit 1
fi

echo "Fetching result for UUID: $resolved_result_uuid"
curl --fail -sS -H "X-API-Key: ${RESULT_SERVER_KEY}" -o "results/result0.json" \
  "${RESULT_SERVER}/api/query/result/${resolved_result_uuid}"
echo "Fetched result to results/result0.json"

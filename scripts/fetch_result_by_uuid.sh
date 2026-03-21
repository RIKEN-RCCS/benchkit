#!/bin/bash
# Fetch a benchmark result JSON from the result server by UUID.
# Saves the result to results/result0.json for subsequent estimation.
#
# Required CI variables:
#   estimate_uuid  - UUID of the benchmark result to fetch
#   code           - Program code name (e.g., "qws")
#   RESULT_SERVER  - Base URL of the result server
set -euo pipefail

if [[ -z "${estimate_uuid:-}" || -z "${code:-}" ]]; then
  echo "ERROR: Both estimate_uuid and code must be specified" >&2
  exit 1
fi

mkdir -p results

echo "Fetching result for UUID: $estimate_uuid"
curl --fail -sS -o "results/result0.json" \
  "${RESULT_SERVER}/api/result/${estimate_uuid}"
echo "Fetched result to results/result0.json"

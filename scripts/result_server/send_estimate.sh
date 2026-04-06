#!/bin/bash
# Send estimate result JSON files to the result server.
# Follows the same pattern as send_results.sh but targets
# the /api/ingest/estimate endpoint for estimation results.
set -euo pipefail

echo "Sending estimate results to server"

found=0
for json_file in results/estimate*.json; do
  [[ ! -f "$json_file" ]] && continue
  found=1
  echo "Posting $json_file to ${RESULT_SERVER}/api/ingest/estimate"
  curl --fail -sS -X POST "${RESULT_SERVER}/api/ingest/estimate" \
    -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    -H "Content-Type: application/json" \
    --data-binary @"$json_file"
  echo ""
  echo "Sent: $json_file"
done

if [[ "$found" -eq 0 ]]; then
  echo "WARNING: No estimate*.json files found in results/"
fi

echo "All estimate results sent."

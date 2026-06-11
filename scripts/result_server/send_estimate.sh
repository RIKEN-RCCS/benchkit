#!/bin/bash
# Send estimate result JSON files to the result server.
# Follows the same pattern as send_results.sh but targets
# the /api/ingest/estimate endpoint for estimation results.
set -euo pipefail

echo "Sending estimate results to server"

upload_estimation_artifacts() {
  local json_file="$1"
  local source_uuid="$2"
  local archive
  local endpoint
  local endpoints
  local response
  local upload_ok=0

  if [[ ! -d "results/estimation_artifacts" ]] || ! compgen -G "results/estimation_artifacts/*" > /dev/null; then
    echo "No estimation_artifacts directory found for $json_file. Skipping estimation artifact upload."
    return 0
  fi

  if [[ -z "$source_uuid" || "$source_uuid" == "null" ]]; then
    echo "WARNING: Could not resolve source result UUID for $json_file. Skipping estimation artifact upload." >&2
    return 0
  fi

  archive="results/estimation_artifacts_${source_uuid}.tgz"
  tar \
    --exclude='*_prepare' \
    --exclude='*_prepare/*' \
    --exclude='*.ncu-rep' \
    --exclude='profile_raw.csv' \
    --exclude='padata*.tgz' \
    --exclude='*.tgz' \
    -C "results/estimation_artifacts" \
    -czf "$archive" .
  echo "Uploading $archive with source result UUID $source_uuid"

  endpoints=("/api/ingest/estimation-artifacts" "/api/ingest/estimation-inputs")
  for endpoint in "${endpoints[@]}"; do
    if response=$(curl --fail -sS -X POST "${RESULT_SERVER}${endpoint}" \
      -H "X-API-Key: ${RESULT_SERVER_KEY}" \
      -F "id=${source_uuid}" \
      -F "file=@${archive}" 2>&1); then
      upload_ok=1
      break
    fi
    if [[ "$endpoint" == "/api/ingest/estimation-artifacts" ]] && printf '%s\n' "$response" | grep -q '404'; then
      echo "WARNING: ${endpoint} was not available; retrying legacy /api/ingest/estimation-inputs endpoint." >&2
      continue
    fi
    break
  done

  if [[ "$upload_ok" -eq 1 ]]; then
    if [[ -n "$response" ]]; then
      echo "$response"
    fi
    rm -f "$archive"
    echo "Uploaded estimation artifacts for $json_file"
    return 0
  fi

  rm -f "$archive"
  if printf '%s\n' "$response" | grep -q '413'; then
    echo "WARNING: Skipping estimation artifact upload because the server rejected ${archive} as too large (HTTP 413)." >&2
    echo "WARNING: Estimate JSON was already ingested; estimation artifacts remain available as GitLab artifacts." >&2
    return 0
  fi

  echo "ERROR: Failed to upload estimation artifacts for ${json_file}" >&2
  echo "$response" >&2
  return 1
}

found=0
for json_file in results/estimate*.json; do
  [[ ! -f "$json_file" ]] && continue
  found=1
  source_uuid=$(jq -r '
    .estimate_metadata.source_result_uuid
    // .estimate_metadata.source_result.uuid
    // .current_system.benchmark.uuid
    // .current_system.uuid
    // ._server_uuid
    // empty
  ' "$json_file")
  echo "Posting $json_file to ${RESULT_SERVER}/api/ingest/estimate"
  curl --fail -sS -X POST "${RESULT_SERVER}/api/ingest/estimate" \
    -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    -H "Content-Type: application/json" \
    --data-binary @"$json_file"
  echo ""
  echo "Sent: $json_file"
  upload_estimation_artifacts "$json_file" "$source_uuid"
done

if [[ "$found" -eq 0 ]]; then
  echo "WARNING: No estimate*.json files found in results/"
fi

echo "All estimate results sent."

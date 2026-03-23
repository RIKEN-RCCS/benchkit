#!/bin/bash
set -euo pipefail

echo "Sending results to server"

ls results/

# Loop over all result*.json files
for json_file in results/result*.json; do
  [[ ! -f "$json_file" ]] && continue

  echo "Processing $json_file"
  cat "$json_file"

  echo "Posting $json_file to ${RESULT_SERVER}/api/ingest/result"

  # Post JSON and capture response
  response=$(curl --fail -sS -X POST "${RESULT_SERVER}/api/ingest/result" \
    -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    -H "Content-Type: application/json" \
    --data-binary @"$json_file")

  echo "Response: $response"

  # Extract UUID from response without jq
  uuid=$(echo "$response" | grep -o '"id":"[^"]*"' | sed -E 's/"id":"([^"]*)"/\1/')
  if [[ -z "$uuid" ]]; then
    echo "ERROR: Failed to extract id from response" >&2
    exit 1
  fi
  echo "Extracted UUID: $uuid"

  # Extract timestamp from response without jq
  timestamp=$(echo "$response" | grep -o '"timestamp":"[^"]*"' | sed -E 's/"timestamp":"([^"]*)"/\1/')
  if [[ -z "$timestamp" ]]; then
    echo "ERROR: Failed to extract timestamp from response" >&2
    exit 1
  fi
  echo "Extracted TIMESTAMP: $timestamp"

  # Write uuid and timestamp back into the Result_JSON for downstream use (estimate.sh)
  tmp_file="${json_file}.tmp"
  python3 -c "
import json, sys
with open('${json_file}', 'r') as f:
    d = json.load(f)
d['_server_uuid'] = '${uuid}'
d['_server_timestamp'] = '${timestamp}'
with open('${tmp_file}', 'w') as f:
    json.dump(d, f, indent=2)
" && mv "$tmp_file" "$json_file"
  echo "Wrote _server_uuid and _server_timestamp back to $json_file"

  # Determine corresponding TGZ name
  tgz_base="padata"

  if [[ "$json_file" =~ result([0-9]+)\.json$ ]]; then
    num="${BASH_REMATCH[1]}"
    tgz_file="results/${tgz_base}${num}.tgz"
  else
    tgz_file="results/${tgz_base}.tgz"
  fi

  echo tgz_file $tgz_file

  
  # Upload TGZ if it exists
  if [[ -f "$tgz_file" ]]; then
    echo "Uploading $tgz_file with UUID $uuid"
    curl --fail -sS -X POST "${RESULT_SERVER}/api/ingest/padata" \
      -H "X-API-Key: ${RESULT_SERVER_KEY}" \
      -F "id=${uuid}" \
      -F "timestamp=${timestamp}" \
      -F "file=@${tgz_file}"
    echo "Uploaded $tgz_file"
  else
    echo "No matching TGZ found for $json_file (expected: $tgz_file). Skipping upload."
  fi

done

echo "All done."

#!/bin/bash
set -euo pipefail

echo "Sending results to server"

ls results/

# Loop over all result*.json files
for json_file in results/result*.json; do
  [[ ! -f "$json_file" ]] && continue

  echo "Processing $json_file"
  cat "$json_file"

  echo "Posting $json_file to http://${RESULT_SERVER}/write-api"

  # Post JSON and capture response
  response=$(curl --fail -sS -X POST "http://${RESULT_SERVER}/write-api" \
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
    echo "ERROR: Failed to extract id from response" >&2
    exit 1
  fi
  echo "Extracted TIMESTAMP: $timestamp"

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
    curl --fail -sS -X POST "http://${RESULT_SERVER}/upload-tgz" \
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

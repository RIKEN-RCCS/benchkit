#!/bin/bash
set -euo pipefail

echo "Sending results to server"

ls results/

meta_file="results/server_result_meta.json"
echo "{}" > "$meta_file"

build_profile_data_summary() {
  local tgz_file="$1"

  if [[ ! -f "$tgz_file" ]]; then
    printf '%s' ""
    return 0
  fi

  local meta_json
  meta_json=$(tar -xOf "$tgz_file" --wildcards '*/meta.json' 2>/dev/null || true)
  if [[ -z "$meta_json" ]]; then
    printf '%s' ""
    return 0
  fi

  echo "$meta_json" | jq -c '
    {
      tool: .tool,
      level: .level,
      report_format: .report_format,
      raw_dir: .raw_dir,
      run_count: ((.runs // []) | length),
      events: ((.runs // []) | map(.event) | map(select(. != null and . != ""))),
      report_kinds: ((.runs // []) | map(.reports // []) | add | map(.kind) | unique)
    }
  ' 2>/dev/null || true
}

# Loop over all result*.json files
for json_file in results/result*.json; do
  [[ ! -f "$json_file" ]] && continue

  # Determine corresponding TGZ name
  tgz_base="padata"

  if [[ "$json_file" =~ result([0-9]+)\.json$ ]]; then
    num="${BASH_REMATCH[1]}"
    tgz_file="results/${tgz_base}${num}.tgz"
  else
    tgz_file="results/${tgz_base}.tgz"
  fi

  echo tgz_file $tgz_file

  profile_data_summary=$(build_profile_data_summary "$tgz_file")
  if [[ -n "$profile_data_summary" ]]; then
    tmp_file="${json_file}.tmp"
    jq --argjson profile_data "$profile_data_summary" \
      '. + { profile_data: $profile_data }' \
      "$json_file" > "$tmp_file"
    mv "$tmp_file" "$json_file"
    echo "Embedded profile_data summary into $json_file"
  fi

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
  jq \
    --arg uuid "$uuid" \
    --arg timestamp "$timestamp" \
    '. + { _server_uuid: $uuid, _server_timestamp: $timestamp }' \
    "$json_file" > "$tmp_file"
  mv "$tmp_file" "$json_file"
  echo "Wrote _server_uuid and _server_timestamp back to $json_file"

  tmp_meta_file="${meta_file}.tmp"
  jq \
    --arg file "$(basename "$json_file")" \
    --arg uuid "$uuid" \
    --arg timestamp "$timestamp" \
    '. + { ($file): { uuid: $uuid, timestamp: $timestamp } }' \
    "$meta_file" > "$tmp_meta_file"
  mv "$tmp_meta_file" "$meta_file"
  echo "Updated result metadata manifest: $meta_file"

  
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

  if [[ -d "results/estimation_inputs" ]] && compgen -G "results/estimation_inputs/*" > /dev/null; then
    estimation_inputs_archive="results/estimation_inputs_${uuid}.tgz"
    tar -C "results/estimation_inputs" -czf "$estimation_inputs_archive" .
    echo "Uploading $estimation_inputs_archive with UUID $uuid"
    curl --fail -sS -X POST "${RESULT_SERVER}/api/ingest/estimation-inputs" \
      -H "X-API-Key: ${RESULT_SERVER_KEY}" \
      -F "id=${uuid}" \
      -F "file=@${estimation_inputs_archive}"
    rm -f "$estimation_inputs_archive"
    echo "Uploaded estimation inputs for $json_file"
  else
    echo "No estimation_inputs directory found for $json_file. Skipping estimation input upload."
  fi

done

echo "Final result metadata manifest:"
cat "$meta_file"

echo "All done."

#!/bin/bash
set -euo pipefail

echo "Sending results to server"

source "$(dirname "${BASH_SOURCE[0]}")/client_env.sh"

bk_result_server_require_env

ls results/

meta_file="results/server_result_meta.json"
echo "{}" > "$meta_file"

# Backfill profile_data for older result JSONs that were produced before
# result.sh learned to embed profiler summaries. The summary comes from
# bk_profiler_artifact/meta.json inside the matching padata archive; raw
# profiler files stay in the archive and are uploaded separately below.
build_profile_data_summary() {
  local tgz_file="$1"

  if [[ ! -f "$tgz_file" ]]; then
    printf '%s' ""
    return 0
  fi

  local meta_member
  meta_member=$(tar -tzf "$tgz_file" 2>/dev/null | grep 'meta\.json$' | head -n 1 || true)
  if [[ -z "$meta_member" ]]; then
    printf '%s' ""
    return 0
  fi

  local meta_json
  meta_json=$(tar -xOf "$tgz_file" "$meta_member" 2>/dev/null || true)
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
      events: (
        if .tool == "fapp"
        then ((.runs // []) | map(.event) | map(select(. != null and . != "")))
        else []
        end
      ),
      ncu_options: (
        if .tool == "ncu" and ((.measurement.ncu_options // null) | type) == "array"
        then .measurement.ncu_options
        else []
        end
      ),
      report_kinds: ((.runs // []) | map(.reports // []) | add | map(.kind) | unique)
    }
  ' 2>/dev/null || true
}

build_profile_data_summary_for_archives() {
  local summaries_file
  summaries_file=$(mktemp)
  local summary
  local archive_count=0

  for tgz_file in "$@"; do
    summary=$(build_profile_data_summary "$tgz_file")
    if [[ -n "$summary" ]]; then
      printf '%s\n' "$summary" >> "$summaries_file"
      archive_count=$((archive_count + 1))
    fi
  done

  if [[ "$archive_count" -eq 0 ]]; then
    rm -f "$summaries_file"
    printf '%s' ""
    return 0
  fi

  if [[ "$archive_count" -eq 1 ]]; then
    cat "$summaries_file"
    rm -f "$summaries_file"
    return 0
  fi

  jq -s -c '
    {
      tool: ((map(.tool) | map(select(. != null and . != "")) | unique) as $tools |
        if ($tools | length) == 1 then $tools[0] else "multiple" end),
      level: ((map(.level) | map(select(. != null and . != "")) | unique) as $levels |
        if ($levels | length) == 1 then $levels[0] else "multiple" end),
      report_format: ((map(.report_format) | map(select(. != null and . != "")) | unique) as $formats |
        if ($formats | length) == 1 then $formats[0] else "multiple" end),
      raw_dir: "multiple",
      run_count: (map(.run_count // 0) | add),
      events: (map(.events // []) | add | unique),
      ncu_options: (map(.ncu_options // []) | add | unique),
      report_kinds: (map(.report_kinds // []) | add | unique),
      archive_count: length
    }
  ' "$summaries_file" 2>/dev/null || true
  rm -f "$summaries_file"
}

is_safe_local_padata_path() {
  local artifact_path="$1"

  case "$artifact_path" in
    results/*.tgz|results/*.tar.gz) ;;
    *) return 1 ;;
  esac

  case "$artifact_path" in
    /*|*"/../"*|../*|*"/.."|*\\*) return 1 ;;
  esac

  [[ -f "$artifact_path" ]]
}

collect_padata_archives_for_result() {
  local json_file="$1"
  local legacy_tgz_file="$2"
  declare -A seen_archives=()

  if [[ -f "$legacy_tgz_file" ]]; then
    seen_archives["$legacy_tgz_file"]=1
    printf '%s\t%s\n' "$legacy_tgz_file" ""
  fi

  while IFS= read -r artifact_path; do
    [[ -n "$artifact_path" ]] || continue
    if is_safe_local_padata_path "$artifact_path" && [[ -z "${seen_archives[$artifact_path]:-}" ]]; then
      seen_archives["$artifact_path"]=1
      printf '%s\t%s\n' "$artifact_path" "$artifact_path"
    fi
  done < <(jq -r '
    (.fom_breakdown.sections // [])[]?
    | (.artifacts // [])[]?
    | select(.type == "file_reference")
    | .path // empty
  ' "$json_file" 2>/dev/null || true)
}

upload_padata_archive() {
  local tgz_file="$1"
  local uuid="$2"
  local timestamp="$3"
  local artifact_path="${4:-}"
  local response

  echo "Uploading $tgz_file with UUID $uuid"
  local curl_auth_args=()
  local curl_form_args=(
    -F "id=${uuid}"
    -F "timestamp=${timestamp}"
    -F "file=@${tgz_file}"
  )
  if [[ -n "$artifact_path" ]]; then
    curl_form_args+=(-F "artifact_path=${artifact_path}")
  fi
  bk_result_server_set_curl_args
  if response=$(curl --fail -sS "${curl_auth_args[@]}" -X POST "${RESULT_SERVER}/api/ingest/padata" \
    "${curl_form_args[@]}" 2>&1); then
    if [[ -n "$response" ]]; then
      echo "$response"
    fi
    echo "Uploaded $tgz_file"
    return 0
  fi

  if printf '%s\n' "$response" | grep -q '413'; then
    echo "WARNING: Skipping padata upload because the server rejected ${tgz_file} as too large (HTTP 413)." >&2
    echo "WARNING: Result JSON was already ingested; the padata archive remains available as a GitLab artifact for downstream jobs." >&2
    return 0
  fi

  echo "ERROR: Failed to upload ${tgz_file}" >&2
  echo "$response" >&2
  return 1
}

# Loop over all result*.json files
for json_file in results/result*.json; do
  [[ ! -f "$json_file" ]] && continue

  # Match result12.json with padata12.tgz, and result.json with padata.tgz.
  tgz_base="padata"

  if [[ "$json_file" =~ result([0-9]+)\.json$ ]]; then
    num="${BASH_REMATCH[1]}"
    tgz_file="results/${tgz_base}${num}.tgz"
  else
    tgz_file="results/${tgz_base}.tgz"
  fi

  echo tgz_file $tgz_file

  padata_archive_paths=()
  padata_archive_specs=()
  while IFS=$'\t' read -r archive_path artifact_path; do
    [[ -n "$archive_path" ]] || continue
    padata_archive_paths+=("$archive_path")
    padata_archive_specs+=("${archive_path}"$'\t'"${artifact_path}")
  done < <(collect_padata_archives_for_result "$json_file" "$tgz_file")

  profile_data_summary=$(build_profile_data_summary_for_archives "${padata_archive_paths[@]}")
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
  curl_auth_args=()
  bk_result_server_set_curl_args
  response=$(curl --fail -sS "${curl_auth_args[@]}" -X POST "${RESULT_SERVER}/api/ingest/result" \
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

  
  # Upload matching profiler archives. Legacy resultN.json/padataN.tgz pairs are
  # kept, and section artifact archives are sent with artifact_path so the server
  # can keep multiple archives for the same result UUID.
  if [[ "${#padata_archive_specs[@]}" -gt 0 ]]; then
    for archive_spec in "${padata_archive_specs[@]}"; do
      IFS=$'\t' read -r archive_path artifact_path <<< "$archive_spec"
      upload_padata_archive "$archive_path" "$uuid" "$timestamp" "$artifact_path"
    done
  else
    echo "No profiler TGZ found for $json_file (expected: $tgz_file or section artifact padata archives). Skipping upload."
  fi

done

echo "Final result metadata manifest:"
cat "$meta_file"

echo "All done."

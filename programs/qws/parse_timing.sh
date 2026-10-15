#!/bin/bash
# parse_timing.sh - Normalize QWS timing output into a small JSON artifact.

set -euo pipefail

qws_timing_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "${qws_timing_dir}/../../scripts/json_output.sh"

qws_extract_fom_from_log() {
  local log_file="$1"

  awk '
    /etime for sovler/ || /etime for solver/ {
      count += 1
      if (count == 2) {
        printf "%.3f\n", $5 + 0
        exit
      }
    }
  ' "$log_file"
}

qws_extract_timing_table() {
  local log_file="$1"

  awk '
    function is_number(value) {
      return value ~ /^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$/
    }
    /^[[:space:]]*rank[[:space:]]+func_id[[:space:]]+calls[[:space:]]+total[(]s[)][[:space:]]+average[(]s[)]/ {
      in_table = 1
      next
    }
    in_table && /^[[:space:]]*end[[:space:]]*$/ {
      in_table = 0
      next
    }
    in_table && NF >= 5 && $1 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && is_number($4) && is_number($5) {
      printf "%s\t%s\t%s\t%.12g\t%.12g\n", $1, $2, $3, $4 + 0, $5 + 0
    }
  ' "$log_file"
}

qws_timing_schema_json() {
  local log_file="$1"
  local line record_type rest token key value
  local record_separator="" field_separator=""
  local tokens=()

  printf '['
  while IFS= read -r line; do
    read -r record_type rest <<< "$line"
    [[ "$record_type" =~ ^QWS_TIMER_SCHEMA(_[A-Z_]+)?$ ]] || continue
    printf '%s{' "$record_separator"
    printf '"record_type":'
    bk_json_quote "$record_type"
    printf ',"fields":{'
    field_separator=""
    read -r -a tokens <<< "$rest"
    for token in "${tokens[@]}"; do
      [[ "$token" == *:* ]] || continue
      key=${token%%:*}
      value=${token#*:}
      [[ -n "$key" ]] || continue
      printf '%s' "$field_separator"
      bk_json_quote "$key"
      printf ':'
      bk_json_quote "$value"
      field_separator=,
    done
    printf '}}'
    record_separator=,
  done < <(awk '/^QWS_TIMER_SCHEMA/ { print }' "$log_file")
  printf ']'
}

qws_timing_table_json() {
  local log_file="$1"
  local rank id calls total_seconds average_seconds
  local separator=""

  printf '['
  while IFS=$'\t' read -r rank id calls total_seconds average_seconds; do
    [[ -n "$average_seconds" ]] || continue
    printf '%s{"rank":%s,"id":' "$separator" "$rank"
    bk_json_quote "$id"
    printf ',"calls":%s,"total_seconds":%s,"average_seconds":%s}' \
      "$calls" "$total_seconds" "$average_seconds"
    separator=,
  done < <(qws_extract_timing_table "$log_file")
  printf ']'
}

qws_emit_timing_artifact_json() {
  local log_file="$1"
  local exp="$2"
  local fom="${3:-}"
  local schema_json
  local timers_json
  local source_log_name
  local timer_count
  local schema_record_count
  local has_timing_table=false
  local has_overlap_probe_schema=false

  if [[ ! -f "$log_file" ]]; then
    echo "QWS timing log was not found: ${log_file}" >&2
    return 1
  fi

  source_log_name=$(basename "$log_file")
  schema_json=$(qws_timing_schema_json "$log_file")
  timers_json=$(qws_timing_table_json "$log_file")
  timer_count=$(qws_extract_timing_table "$log_file" | awk 'END { print NR + 0 }')
  schema_record_count=$(awk '/^QWS_TIMER_SCHEMA/ { count += 1 } END { print count + 0 }' "$log_file")
  if (( timer_count > 0 )); then
    has_timing_table=true
  fi
  if awk '/^QWS_TIMER_SCHEMA([[:space:]]|$)/ && /(^|[[:space:]])target:overlap_probe([[:space:]]|$)/ { found=1 } END { exit !found }' "$log_file"; then
    has_overlap_probe_schema=true
  fi

  printf '{"schema_version":1,"producer":"qws","kind":"qws_timing_observation","exp":'
  bk_json_quote "$exp"
  printf ',"source_log":'
  bk_json_quote "$source_log_name"
  printf ',"schema":%s,"timers":%s' "$schema_json" "$timers_json"
  printf ',"summary":{"timer_count":%s,"schema_record_count":%s,"has_timing_table":%s,"has_overlap_probe_schema":%s}' \
    "$timer_count" "$schema_record_count" "$has_timing_table" "$has_overlap_probe_schema"
  if [[ "$fom" =~ ^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$ ]]; then
    printf ',"fom_seconds":%s' "$fom"
  fi
  printf '}\n'
}

qws_observe_timing() {
  if grep -Eq '^[[:space:]]*rank[[:space:]]+func_id[[:space:]]+calls[[:space:]]+total[(]s[)][[:space:]]+average[(]s[)]|^QWS_TIMER_SCHEMA' "$1"; then
    qws_emit_timing_artifact_json "$@"
  fi
}

qws_write_timing_artifact() {
  local log_file="$1"
  local exp="$2"
  local output_file="$3"
  local fom="${4:-}"
  local tmp_file

  if [[ ! -f "$log_file" ]]; then
    echo "QWS timing artifact skipped; log was not found: ${log_file}" >&2
    return 0
  fi
  if ! grep -Eq '^[[:space:]]*rank[[:space:]]+func_id[[:space:]]+calls[[:space:]]+total[(]s[)][[:space:]]+average[(]s[)]|^QWS_TIMER_SCHEMA' "$log_file"; then
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"
  tmp_file=$(mktemp "${output_file}.tmp.XXXXXX")
  if qws_emit_timing_artifact_json "$log_file" "$exp" "$fom" > "$tmp_file"; then
    mv "$tmp_file" "$output_file"
  else
    rm -f "$tmp_file"
    echo "QWS timing artifact skipped; failed to parse ${log_file}" >&2
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ $# -lt 2 || $# -gt 4 ]]; then
    echo "Usage: $0 <qws-log-file> <exp> [output-json] [fom-seconds]" >&2
    exit 2
  fi

  if [[ $# -ge 3 ]]; then
    qws_write_timing_artifact "$1" "$2" "$3" "${4:-}"
  else
    qws_emit_timing_artifact_json "$1" "$2"
  fi
fi

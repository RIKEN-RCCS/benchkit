#!/bin/bash
# parse_timing.sh - Normalize QWS timing output into a small JSON artifact.

set -euo pipefail

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

  awk '/^QWS_TIMER_SCHEMA/ { print }' "$log_file" | jq -Rsc '
    def kv_token:
      split(":") as $parts
      | select(($parts | length) >= 2)
      | {key: $parts[0], value: ($parts[1:] | join(":"))};
    [
      split("\n")[]
      | select(length > 0)
      | capture("^(?<record_type>QWS_TIMER_SCHEMA(?:_[A-Z_]+)?)\\s*(?<rest>.*)$")?
      | {
          record_type: .record_type,
          fields: (
            .rest
            | split(" ")
            | map(select(length > 0) | kv_token)
            | from_entries
          )
        }
    ]
  '
}

qws_timing_table_json() {
  local log_file="$1"

  qws_extract_timing_table "$log_file" | jq -Rnc '
    [
      inputs
      | split("\t")
      | select(length == 5)
      | {
          rank: (.[0] | tonumber),
          id: .[1],
          calls: (.[2] | tonumber),
          total_seconds: (.[3] | tonumber),
          average_seconds: (.[4] | tonumber)
        }
    ]
  '
}

qws_emit_timing_artifact_json() {
  local log_file="$1"
  local exp="$2"
  local fom="${3:-}"
  local schema_json
  local timers_json
  local source_log_name

  if [[ ! -f "$log_file" ]]; then
    echo "QWS timing log was not found: ${log_file}" >&2
    return 1
  fi

  source_log_name=$(basename "$log_file")
  schema_json=$(qws_timing_schema_json "$log_file")
  timers_json=$(qws_timing_table_json "$log_file")

  jq -n \
    --arg exp "$exp" \
    --arg source_log "$source_log_name" \
    --arg fom "$fom" \
    --argjson schema "$schema_json" \
    --argjson timers "$timers_json" '
      def number_text:
        test("^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$");
      {
        schema_version: 1,
        producer: "qws",
        kind: "qws_timing_observation",
        exp: $exp,
        source_log: $source_log,
        schema: $schema,
        timers: $timers,
        summary: {
          timer_count: ($timers | length),
          schema_record_count: ($schema | length),
          has_timing_table: (($timers | length) > 0),
          has_overlap_probe_schema: (
            any($schema[]?; .record_type == "QWS_TIMER_SCHEMA" and .fields.target == "overlap_probe")
          )
        }
      }
      + (if ($fom | number_text) then {fom_seconds: ($fom | tonumber)} else {} end)
    '
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
  if ! command -v jq >/dev/null 2>&1; then
    echo "QWS timing artifact skipped; jq is not available" >&2
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

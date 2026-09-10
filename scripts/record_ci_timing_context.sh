#!/bin/bash
set -euo pipefail

stage="${1:-unknown}"
output="${2:-results/ci_timing_context.json}"

timestamp_to_epoch() {
  local value="$1"
  [ -n "$value" ] || return 1
  date -u -d "$value" +%s 2>/dev/null
}

value_with_source() {
  local name="$1"
  local custom_name="CUSTOM_ENV_${name}"
  if [ -n "${!name:-}" ]; then
    printf '%s\t%s\n' "${!name}" "$name"
    return 0
  fi
  if [ -n "${!custom_name:-}" ]; then
    printf '%s\t%s\n' "${!custom_name}" "$custom_name"
    return 0
  fi
  printf '\t\n'
}

if ! command -v jq >/dev/null 2>&1; then
  echo "CI timing context not recorded: jq not found"
  exit 0
fi

mkdir -p "$(dirname "$output")"

ci_job_started_at=""
ci_job_started_at_source=""
ci_pipeline_created_at=""
ci_pipeline_created_at_source=""
parent_pipeline_created_at=""
parent_pipeline_created_at_source=""

IFS=$'\t' read -r ci_job_started_at ci_job_started_at_source < <(value_with_source "CI_JOB_STARTED_AT")
IFS=$'\t' read -r ci_pipeline_created_at ci_pipeline_created_at_source < <(value_with_source "CI_PIPELINE_CREATED_AT")
IFS=$'\t' read -r parent_pipeline_created_at parent_pipeline_created_at_source < <(value_with_source "PARENT_PIPELINE_CREATED_AT")

ci_job_started_epoch=""
if [ -n "$ci_job_started_at" ]; then
  ci_job_started_epoch=$(timestamp_to_epoch "$ci_job_started_at" || true)
fi

jq -n \
  --arg stage "$stage" \
  --arg collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg ci_job_started_at "$ci_job_started_at" \
  --arg ci_job_started_at_source "$ci_job_started_at_source" \
  --arg ci_job_started_epoch "$ci_job_started_epoch" \
  --arg ci_pipeline_created_at "$ci_pipeline_created_at" \
  --arg ci_pipeline_created_at_source "$ci_pipeline_created_at_source" \
  --arg parent_pipeline_created_at "$parent_pipeline_created_at" \
  --arg parent_pipeline_created_at_source "$parent_pipeline_created_at_source" \
  '
  {schema_version: 1, stage: $stage, collected_at: $collected_at}
  + (if $ci_job_started_at != "" then {
      ci_job_started_at: $ci_job_started_at,
      ci_job_started_at_source: $ci_job_started_at_source
    } else {} end)
  + (if $ci_job_started_epoch != "" then {
      ci_job_started_epoch: ($ci_job_started_epoch | tonumber)
    } else {} end)
  + (if $ci_pipeline_created_at != "" then {
      ci_pipeline_created_at: $ci_pipeline_created_at,
      ci_pipeline_created_at_source: $ci_pipeline_created_at_source
    } else {} end)
  + (if $parent_pipeline_created_at != "" then {
      parent_pipeline_created_at: $parent_pipeline_created_at,
      parent_pipeline_created_at_source: $parent_pipeline_created_at_source
    } else {} end)
  ' > "$output"

echo "Recorded CI timing context: stage=${stage} ci_job_started_at=${ci_job_started_at:-not_available}"

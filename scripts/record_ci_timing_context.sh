#!/bin/bash
set -euo pipefail

# shellcheck source=scripts/json_output.sh
source "$(dirname "${BASH_SOURCE[0]}")/json_output.sh"

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

fields=(json schema_version 1 string stage "$stage"
  string collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
if [ -n "$ci_job_started_at" ]; then
  fields+=(string ci_job_started_at "$ci_job_started_at"
    string ci_job_started_at_source "$ci_job_started_at_source")
fi
if [[ "$ci_job_started_epoch" =~ ^-?(0|[1-9][0-9]*)$ ]]; then
  fields+=(json ci_job_started_epoch "$ci_job_started_epoch")
fi
if [ -n "$ci_pipeline_created_at" ]; then
  fields+=(string ci_pipeline_created_at "$ci_pipeline_created_at"
    string ci_pipeline_created_at_source "$ci_pipeline_created_at_source")
fi
if [ -n "$parent_pipeline_created_at" ]; then
  fields+=(string parent_pipeline_created_at "$parent_pipeline_created_at"
    string parent_pipeline_created_at_source "$parent_pipeline_created_at_source")
fi
bk_json_object "${fields[@]}" > "$output"

echo "Recorded CI timing context: stage=${stage} ci_job_started_at=${ci_job_started_at:-not_available}"

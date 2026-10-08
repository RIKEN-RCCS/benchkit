#!/bin/bash
# Retain execution evidence even when an application produces no FOM.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/scripts/json_output.sh"
[ "$#" -gt 0 ] || exit 2
results="${PWD}/results"
started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null) || commit=""
write_record() {
  local status=$1 code=${2:-null} temporary
  temporary=$(mktemp "$results/.execution.XXXXXXXX") || return 1
  if bk_json_object json schema_version 1 string kind benchmark_execution \
      string status "$status" string started_at "$started" \
      string observed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      json exit_code "$code" string benchkit_commit "$commit" \
      string ci_job_id "${CI_JOB_ID:-}" string ci_pipeline_id "${CI_PIPELINE_ID:-}" \
      > "$temporary" && mv -f -- "$temporary" "$results/execution.json"; then
    return 0
  fi
  rm -f -- "$temporary"
  return 1
}
if mkdir -p -- "$results" && write_record running; then
  bash "$@" 2>&1 | tee --output-error=warn "$results/execution.log"
  statuses=("${PIPESTATUS[@]}")
  code=${statuses[0]}
  [ "${statuses[1]}" -eq 0 ] || echo 'Benchkit run: execution log could not be stored' >&2
  status=completed
  [ "$code" -eq 0 ] || status=failed
  write_record "$status" "$code" || echo 'Benchkit run: final execution record unavailable' >&2
  exit "$code"
fi
echo 'Benchkit run: execution records unavailable; running application' >&2
exec bash "$@"

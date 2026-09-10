#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping CI timing context test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/results"

export CI_JOB_STARTED_AT="2026-09-10T03:14:48Z"
export CI_PIPELINE_CREATED_AT="2026-09-10T03:14:17Z"
export PARENT_PIPELINE_CREATED_AT="2026-09-10T03:14:09Z"

expected_job_started_epoch=$(date -u -d "$CI_JOB_STARTED_AT" +%s)

bash "${REPO_DIR}/scripts/record_ci_timing_context.sh" run "${TMP_DIR}/results/ci_timing_context.json" >/dev/null

jq -e \
  --argjson expected_job_started_epoch "$expected_job_started_epoch" \
  '
  .schema_version == 1 and
  .stage == "run" and
  .ci_job_started_at == "2026-09-10T03:14:48Z" and
  .ci_job_started_at_source == "CI_JOB_STARTED_AT" and
  .ci_job_started_epoch == $expected_job_started_epoch and
  .ci_pipeline_created_at == "2026-09-10T03:14:17Z" and
  .parent_pipeline_created_at == "2026-09-10T03:14:09Z"
  ' "${TMP_DIR}/results/ci_timing_context.json" >/dev/null

printf '%s\n' "$((expected_job_started_epoch - 20))" > "${TMP_DIR}/results/build_start"
printf '%s\n' "$((expected_job_started_epoch - 10))" > "${TMP_DIR}/results/build_end"
printf '%s\n' "$((expected_job_started_epoch + 317))" > "${TMP_DIR}/results/run_start"
printf '%s\n' "$((expected_job_started_epoch + 377))" > "${TMP_DIR}/results/run_end"

pushd "${TMP_DIR}" >/dev/null
bash "${REPO_DIR}/scripts/collect_timing.sh" >/dev/null
popd >/dev/null

jq -e '
  .build_time == 10 and
  .queue_time == 0 and
  .queue_time_source == "not_measured" and
  .scheduler_queue_time == 317 and
  .scheduler_queue_time_source == "gitlab_job_started_at" and
  .run_time == 60
' "${TMP_DIR}/results/pipeline_timing.json" >/dev/null

mkdir -p "${TMP_DIR}/custom/results"
unset CI_JOB_STARTED_AT
export CUSTOM_ENV_CI_JOB_STARTED_AT="2026-09-10T03:20:00Z"
bash "${REPO_DIR}/scripts/record_ci_timing_context.sh" build_run "${TMP_DIR}/custom/results/ci_timing_context.json" >/dev/null
jq -e '
  .stage == "build_run" and
  .ci_job_started_at == "2026-09-10T03:20:00Z" and
  .ci_job_started_at_source == "CUSTOM_ENV_CI_JOB_STARTED_AT" and
  (.ci_job_started_epoch | type) == "number"
' "${TMP_DIR}/custom/results/ci_timing_context.json" >/dev/null

mkdir -p "${TMP_DIR}/invalid/results"
cat > "${TMP_DIR}/invalid/results/ci_timing_context.json" <<'EOF'
{
  "schema_version": 1,
  "stage": "run",
  "ci_job_started_epoch": 200
}
EOF
printf '100\n' > "${TMP_DIR}/invalid/results/run_start"
printf '120\n' > "${TMP_DIR}/invalid/results/run_end"
pushd "${TMP_DIR}/invalid" >/dev/null
bash "${REPO_DIR}/scripts/collect_timing.sh" >/dev/null
popd >/dev/null

jq -e '
  .run_time == 20 and
  (.scheduler_queue_time? == null) and
  (.scheduler_queue_time_source? == null)
' "${TMP_DIR}/invalid/results/pipeline_timing.json" >/dev/null

echo "CI timing context test passed"

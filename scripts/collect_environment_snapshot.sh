#!/bin/bash
set -euo pipefail

out_file="${1:-results/environment_snapshot.json}"
snapshot_stage="${BK_SNAPSHOT_STAGE:-unknown}"
mkdir -p "$(dirname "$out_file")"

json_string_array() {
  jq -R -s -c 'split("\n") | map(select(length > 0))'
}

command_path() {
  command -v "$1" 2>/dev/null || true
}

command_version() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" 2>/dev/null | head -n 1 || true
  fi
}

module_list_json="[]"
if command -v module >/dev/null 2>&1; then
  module_list_json=$(module -t list 2>&1 | sed '/^No Modulefiles Currently Loaded/d' | json_string_array)
elif [ -n "${LOADEDMODULES:-}" ]; then
  module_list_json=$(printf '%s' "$LOADEDMODULES" | tr ':' '\n' | json_string_array)
fi

git_commit=""
git_branch=""
git_dirty=""
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_commit=$(git rev-parse HEAD 2>/dev/null || true)
  git_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
    git_dirty="true"
  else
    git_dirty="false"
  fi
fi

scheduler_kind="unknown"
if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
  scheduler_kind="slurm"
elif [ -n "${PBS_JOBID:-}" ]; then
  scheduler_kind="pbs"
elif [ -n "${JACAMAR_CI:-}" ] || [ -n "${JACAMAR_SCHEDULER_ACTION:-}" ]; then
  scheduler_kind="jacamar"
fi

hostname_value=$(hostname 2>/dev/null || true)
uname_value=$(uname -srmo 2>/dev/null || uname -a 2>/dev/null || true)
cpu_model=$(awk -F: '/model name|Hardware|Processor/ {gsub(/^ +/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null || true)

jq -n \
  --arg schema_version "1" \
  --arg stage "$snapshot_stage" \
  --arg collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg system "${BK_SYSTEM:-${system:-}}" \
  --arg allocation_project_id "${BK_ALLOCATION_PROJECT_ID:-}" \
  --arg runner_description "${CI_RUNNER_DESCRIPTION:-}" \
  --arg runner_id "${CI_RUNNER_ID:-}" \
  --arg runner_tags "${CI_RUNNER_TAGS:-}" \
  --arg hostname "$hostname_value" \
  --arg uname "$uname_value" \
  --arg cpu_model "$cpu_model" \
  --arg scheduler_kind "$scheduler_kind" \
  --arg slurm_job_id "${SLURM_JOB_ID:-${SLURM_JOBID:-}}" \
  --arg slurm_partition "${SLURM_JOB_PARTITION:-}" \
  --arg pbs_jobid "${PBS_JOBID:-}" \
  --arg jacamar_scheduler_action "${JACAMAR_SCHEDULER_ACTION:-}" \
  --arg ci_server "${CI_SERVER_URL:-}" \
  --arg ci_project "${CI_PROJECT_PATH:-}" \
  --arg ci_pipeline_id "${CI_PIPELINE_ID:-}" \
  --arg ci_job_id "${CI_JOB_ID:-}" \
  --arg ci_job_name "${CI_JOB_NAME:-}" \
  --arg ci_commit_ref "${CI_COMMIT_REF_NAME:-}" \
  --arg ci_commit_sha "${CI_COMMIT_SHA:-}" \
  --arg benchkit_commit "$git_commit" \
  --arg benchkit_branch "$git_branch" \
  --arg benchkit_dirty "$git_dirty" \
  --arg gcc_version "$(command_version gcc --version)" \
  --arg mpicc_version "$(command_version mpicc --version)" \
  --arg nvcc_version "$(command_version nvcc --version)" \
  --arg python_version "$(command_version python3 --version)" \
  --argjson modules "$module_list_json" \
  '{
    schema_version: ($schema_version | tonumber),
    stage: $stage,
    collected_at: $collected_at,
    system: {
      name: $system,
      allocation_project_id: $allocation_project_id,
      host: {
        hostname: $hostname,
        uname: $uname,
        cpu_model: $cpu_model
      }
    },
    scheduler: {
      kind: $scheduler_kind,
      slurm_job_id: $slurm_job_id,
      slurm_partition: $slurm_partition,
      pbs_jobid: $pbs_jobid,
      jacamar_scheduler_action: $jacamar_scheduler_action
    },
    runner: {
      description: $runner_description,
      id: $runner_id,
      tags: $runner_tags
    },
    ci: {
      server_url: $ci_server,
      project_path: $ci_project,
      pipeline_id: $ci_pipeline_id,
      job_id: $ci_job_id,
      job_name: $ci_job_name,
      commit_ref_name: $ci_commit_ref,
      commit_sha: $ci_commit_sha
    },
    benchkit: {
      branch: $benchkit_branch,
      commit_hash: $benchkit_commit,
      dirty: $benchkit_dirty
    },
    toolchain: {
      gcc: $gcc_version,
      mpicc: $mpicc_version,
      nvcc: $nvcc_version,
      python3: $python_version,
      modules: $modules
    }
  }' > "$out_file"

echo "Wrote environment snapshot: $out_file"

#!/bin/bash
set -euo pipefail

out_file="${1:-results/environment_snapshot.json}"
snapshot_stage="${BK_SNAPSHOT_STAGE:-unknown}"
mkdir -p "$(dirname "$out_file")"

json_string_array() {
  jq -R -s -c 'split("\n") | map(select(length > 0))'
}

json_empty_object_if_blank() {
  if [ -n "$1" ]; then
    printf '%s' "$1"
  else
    printf '{}'
  fi
}

command_path() {
  command -v "$1" 2>/dev/null || true
}

resolved_command_path() {
  local path="$1"
  if [ -z "$path" ]; then
    printf '%s' ""
    return 0
  fi
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "$path" 2>/dev/null || printf '%s' "$path"
    return 0
  fi
  printf '%s' "$path"
}

command_version() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" 2>/dev/null | head -n 1 || true
  fi
}

snapshot_command_version() {
  local cmd="$1"
  case "$cmd" in
    python|python3|python3.*)
      command_version "$cmd" --version
      ;;
    *)
      command_version "$cmd" --version
      ;;
  esac
}

snapshot_tool_commands_json() {
  local default_commands
  default_commands="bash sh cc c++ gcc g++ clang clang++ fcc fccpx frt frtpx "
  default_commands+="mpicc mpicxx mpifcc mpifccpx mpifrt mpifrtpx mpif90 mpifort "
  default_commands+="mpiicc mpiicpc mpiifort gfortran nvcc nvc nvc++ nvfortran "
  default_commands+="cmake make ninja ld ar pkg-config python3 apptainer singularity ncu nsys"

  local commands="${BK_SNAPSHOT_TOOL_COMMANDS:-$default_commands}"
  local cmd path real_path version

  for cmd in $commands; do
    path=$(command_path "$cmd")
    if [ -z "$path" ]; then
      continue
    fi
    real_path=$(resolved_command_path "$path")
    version=$(snapshot_command_version "$cmd")
    jq -n -c \
      --arg name "$cmd" \
      --arg path "$path" \
      --arg real_path "$real_path" \
      --arg version "$version" \
      '{key: $name, value: {path: $path, real_path: $real_path, version: $version}}'
  done | jq -s -c 'from_entries'
}

snapshot_env_is_sensitive() {
  case "$1" in
    *TOKEN*|*SECRET*|*PASSWORD*|*PASSWD*|*PRIVATE*|*CREDENTIAL*|*AUTH*|*KEY*|*CERT*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

snapshot_environment_json() {
  local default_vars
  default_vars="CC CXX FC F77 F90 CPP CPPFLAGS CFLAGS CXXFLAGS FCFLAGS FFLAGS "
  default_vars+="LDFLAGS LIBS PATH LD_LIBRARY_PATH LIBRARY_PATH CPATH PKG_CONFIG_PATH "
  default_vars+="MODULEPATH LOADEDMODULES CUDA_HOME CUDA_PATH NVHPC_ROOT OMP_NUM_THREADS "
  default_vars+="OMPI_CC OMPI_CXX OMPI_FC MPICH_CC MPICH_CXX MPICH_FC"

  local vars="${BK_SNAPSHOT_ENV_VARS:-$default_vars}"
  local name value

  for name in $vars; do
    case "$name" in
      [A-Za-z_][A-Za-z0-9_]*)
        ;;
      *)
        continue
        ;;
    esac
    if [ -z "${!name+x}" ]; then
      continue
    fi
    if snapshot_env_is_sensitive "$name"; then
      value="[redacted]"
    else
      value="${!name}"
    fi
    jq -n -c --arg key "$name" --arg value "$value" '{key: $key, value: $value}'
  done | jq -s -c 'from_entries'
}

module_list_json="[]"
if command -v module >/dev/null 2>&1; then
  module_list_json=$(module -t list 2>&1 | sed '/^No Modulefiles Currently Loaded/d' | json_string_array)
elif [ -n "${LOADEDMODULES:-}" ]; then
  module_list_json=$(printf '%s' "$LOADEDMODULES" | tr ':' '\n' | json_string_array)
fi

tool_commands_json=$(snapshot_tool_commands_json)
tool_environment_json=$(snapshot_environment_json)

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
  --arg container_image_path "${BK_SOURCE_CONTAINER_PATH:-}" \
  --arg container_image_sha256sum "${BK_SOURCE_CONTAINER_SHA256:-}" \
  --argjson modules "$module_list_json" \
  --argjson commands "$(json_empty_object_if_blank "$tool_commands_json")" \
  --argjson environment "$(json_empty_object_if_blank "$tool_environment_json")" \
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
      modules: $modules,
      commands: $commands,
      environment: $environment,
      container: {
        image_path: $container_image_path,
        image_sha256sum: $container_image_sha256sum
      }
    }
  }' > "$out_file"

echo "Wrote environment snapshot: $out_file"

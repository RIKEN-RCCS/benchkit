#!/bin/bash
set -euo pipefail

# shellcheck source=scripts/json_output.sh
source "$(dirname "${BASH_SOURCE[0]}")/json_output.sh"

out_file="${1:-results/environment_snapshot.json}"
snapshot_stage="${BK_SNAPSHOT_STAGE:-unknown}"
mkdir -p "$(dirname "$out_file")"

json_string_array() {
  bk_json_lines_array
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

command_sha256() {
  local path="$1"

  if [ -z "$path" ] || [ ! -f "$path" ] || [ ! -r "$path" ]; then
    printf '%s' ""
    return 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 -r "$path" | awk '{print $1}'
    return 0
  fi
  printf '%s' ""
}

command_version() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" 2>&1 | extract_command_version_line "$cmd" || true
  fi
}

extract_command_version_line() {
  local cmd="$1"

  case "$cmd" in
    nvcc)
      awk '
        /Cuda compilation tools/ {print; found=1; exit}
        /release [0-9][0-9.]*/ {print; found=1; exit}
        NF && first == "" {first=$0}
        END {if (!found && first != "") print first}
      '
      ;;
    nvc|nvc++|nvfortran)
      awk '
        /^[[:space:]]*(nvc|nvc\+\+|nvfortran)[[:space:]]+[0-9]/ {print; found=1; exit}
        NF && first == "" {first=$0}
        END {if (!found && first != "") print first}
      '
      ;;
    *)
      sed -n '/[^[:space:]]/ { p; q; }'
      ;;
  esac
}

snapshot_command_version() {
  local cmd="$1"
  case "$cmd" in
    nvcc|nvc|nvc++|nvfortran)
      command_version "$cmd" -V
      ;;
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
  local cmd path real_path version sha256
  local fields=()
  local -A seen=()

  for cmd in $commands; do
    [ -z "${seen[$cmd]:-}" ] || continue
    seen[$cmd]=1
    path=$(command_path "$cmd")
    if [ -z "$path" ]; then
      continue
    fi
    real_path=$(resolved_command_path "$path")
    version=$(snapshot_command_version "$cmd")
    sha256=$(command_sha256 "$real_path")
    fields+=(json "$cmd" "$(bk_json_object \
      string path "$path" string real_path "$real_path" \
      string version "$version" string sha256 "$sha256")")
  done
  bk_json_object "${fields[@]}"
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
  local fields=()
  local -A seen=()

  for name in $vars; do
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [ -z "${seen[$name]:-}" ] || continue
    seen[$name]=1
    if [ -z "${!name+x}" ]; then
      continue
    fi
    if snapshot_env_is_sensitive "$name"; then
      value="[redacted]"
    else
      value="${!name}"
    fi
    fields+=(string "$name" "$value")
  done
  bk_json_object "${fields[@]}"
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

bk_json_object \
  json schema_version 1 string stage "$snapshot_stage" \
  string collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  json system "$(bk_json_object string name "${BK_SYSTEM:-${system:-}}" \
    string allocation_project_id "${BK_ALLOCATION_PROJECT_ID:-}" \
    json host "$(bk_json_object string hostname "$hostname_value" \
      string uname "$uname_value" string cpu_model "$cpu_model")")" \
  json execution "$(bk_json_object string activity "${BK_EXECUTION_ACTIVITY:-}")" \
  json scheduler "$(bk_json_object string kind "$scheduler_kind" \
    string slurm_job_id "${SLURM_JOB_ID:-${SLURM_JOBID:-}}" \
    string slurm_partition "${SLURM_JOB_PARTITION:-}" string pbs_jobid "${PBS_JOBID:-}" \
    string jacamar_scheduler_action "${JACAMAR_SCHEDULER_ACTION:-}")" \
  json runner "$(bk_json_object string description "${CI_RUNNER_DESCRIPTION:-}" \
    string id "${CI_RUNNER_ID:-}" string tags "${CI_RUNNER_TAGS:-}")" \
  json ci "$(bk_json_object string server_url "${CI_SERVER_URL:-}" \
    string project_path "${CI_PROJECT_PATH:-}" string pipeline_id "${CI_PIPELINE_ID:-}" \
    string job_id "${CI_JOB_ID:-}" string job_name "${CI_JOB_NAME:-}" \
    string commit_ref_name "${CI_COMMIT_REF_NAME:-}" string commit_sha "${CI_COMMIT_SHA:-}")" \
  json benchkit "$(bk_json_object string branch "$git_branch" \
    string commit_hash "$git_commit" string dirty "$git_dirty")" \
  json toolchain "$(bk_json_object string gcc "$(snapshot_command_version gcc)" \
    string mpicc "$(snapshot_command_version mpicc)" string nvcc "$(snapshot_command_version nvcc)" \
    string python3 "$(snapshot_command_version python3)" json modules "$module_list_json" \
    json commands "$tool_commands_json" json environment "$tool_environment_json" \
    json container "$(bk_json_object string image_path "${BK_SOURCE_CONTAINER_PATH:-}" \
      string image_sha256sum "${BK_SOURCE_CONTAINER_SHA256:-}")")" > "$out_file"

echo "Wrote environment snapshot: $out_file"

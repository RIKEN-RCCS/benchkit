#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "bk_build_tool_wrapper: missing tool name" >&2
  exit 127
fi

tool_name="$1"
shift

wrapper_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root="${BK_BENCHKIT_ROOT:-$(cd "${wrapper_dir}/../.." && pwd -P)}"
original_path="${PATH:-}"
path_without_wrapper=""

IFS=':' read -r -a path_entries <<< "$original_path"
for path_entry in "${path_entries[@]}"; do
  display_entry="$path_entry"
  if [ -z "$display_entry" ]; then
    display_entry="."
  fi

  entry_abs="$display_entry"
  if [ -d "$display_entry" ]; then
    entry_abs=$(cd "$display_entry" && pwd -P)
  fi

  if [ "$entry_abs" = "$wrapper_dir" ]; then
    continue
  fi

  if [ -z "$path_without_wrapper" ]; then
    path_without_wrapper="$path_entry"
  else
    path_without_wrapper="${path_without_wrapper}:$path_entry"
  fi
done

real_tool=$(PATH="$path_without_wrapper" command -v "$tool_name" 2>/dev/null || true)
if [ -z "$real_tool" ]; then
  echo "bk_build_tool_wrapper: ${tool_name} not found after removing ${wrapper_dir} from PATH" >&2
  exit 127
fi

json_string() {
  local value="$1"

  if PATH="$path_without_wrapper" command -v python3 >/dev/null 2>&1; then
    JSON_VALUE="$value" PATH="$path_without_wrapper" python3 -c \
      'import json, os; print(json.dumps(os.environ.get("JSON_VALUE", "")))'
    return 0
  fi

  printf '"%s"' "$(printf '%s' "$value" | sed \
    -e 's/\\/\\\\/g' \
    -e 's/"/\\"/g' \
    -e 's/[[:cntrl:]]//g')"
}

fallback_resolved_path() {
  local path="$1"

  if [ -z "$path" ]; then
    printf '%s' ""
    return 0
  fi
  if PATH="$path_without_wrapper" command -v readlink >/dev/null 2>&1; then
    PATH="$path_without_wrapper" readlink -f "$path" 2>/dev/null || printf '%s' "$path"
    return 0
  fi
  printf '%s' "$path"
}

fallback_command_version() {
  local cmd="$1"
  local version_args=("--version")

  if ! PATH="$path_without_wrapper" command -v "$cmd" >/dev/null 2>&1; then
    printf '%s' ""
    return 0
  fi
  case "$cmd" in
    nvcc|nvc|nvc++|nvfortran)
      version_args=("-V")
      ;;
  esac
  PATH="$path_without_wrapper" "$cmd" "${version_args[@]}" 2>&1 | extract_command_version_line "$cmd" || true
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

fallback_commands_json() {
  local default_commands
  default_commands="bash sh cc c++ gcc g++ clang clang++ fcc fccpx frt frtpx "
  default_commands+="mpicc mpicxx mpifcc mpifccpx mpifrt mpifrtpx mpif90 mpifort "
  default_commands+="mpiicc mpiicpc mpiifort gfortran nvcc nvc nvc++ nvfortran "
  default_commands+="cmake make ninja ld ar pkg-config python3 apptainer singularity ncu nsys"

  local commands="${BK_SNAPSHOT_TOOL_COMMANDS:-$default_commands}"
  local first=true
  local cmd path real_path version

  printf '{'
  for cmd in $commands; do
    path=$(PATH="$path_without_wrapper" command -v "$cmd" 2>/dev/null || true)
    if [ -z "$path" ]; then
      continue
    fi
    real_path=$(fallback_resolved_path "$path")
    version=$(fallback_command_version "$cmd")
    if [ "$first" = true ]; then
      first=false
    else
      printf ','
    fi
    printf '%s:{"path":%s,"real_path":%s,"version":%s}' \
      "$(json_string "$cmd")" \
      "$(json_string "$path")" \
      "$(json_string "$real_path")" \
      "$(json_string "$version")"
  done
  printf '}'
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

fallback_environment_json() {
  local default_vars
  default_vars="CC CXX FC F77 F90 CPP CPPFLAGS CFLAGS CXXFLAGS FCFLAGS FFLAGS "
  default_vars+="LDFLAGS LIBS PATH LD_LIBRARY_PATH LIBRARY_PATH CPATH PKG_CONFIG_PATH "
  default_vars+="MODULEPATH LOADEDMODULES CUDA_HOME CUDA_PATH NVHPC_ROOT OMP_NUM_THREADS "
  default_vars+="OMPI_CC OMPI_CXX OMPI_FC MPICH_CC MPICH_CXX MPICH_FC"

  local vars="${BK_SNAPSHOT_ENV_VARS:-$default_vars}"
  local first=true
  local name value

  printf '{'
  for name in $vars; do
    case "$name" in
      [A-Za-z_][A-Za-z0-9_]*)
        ;;
      *)
        continue
        ;;
    esac
    if [ "$name" = "PATH" ]; then
      value="$path_without_wrapper"
    elif [ -z "${!name+x}" ]; then
      continue
    elif snapshot_env_is_sensitive "$name"; then
      value="[redacted]"
    else
      value="${!name}"
    fi
    if [ "$first" = true ]; then
      first=false
    else
      printf ','
    fi
    printf '%s:%s' "$(json_string "$name")" "$(json_string "$value")"
  done
  printf '}'
}

write_fallback_snapshot() {
  local snapshot_file="$1"
  local stage="${BK_SNAPSHOT_STAGE:-build_actual}"
  local collected_at=""
  local hostname_value=""
  local uname_value=""
  local cpu_model=""
  local git_commit=""
  local git_branch=""
  local git_dirty=""
  local commands_json
  local environment_json
  local scheduler_kind="unknown"

  if PATH="$path_without_wrapper" command -v date >/dev/null 2>&1; then
    collected_at=$(PATH="$path_without_wrapper" date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true)
  fi
  if PATH="$path_without_wrapper" command -v hostname >/dev/null 2>&1; then
    hostname_value=$(PATH="$path_without_wrapper" hostname 2>/dev/null || true)
  fi
  if PATH="$path_without_wrapper" command -v uname >/dev/null 2>&1; then
    uname_value=$(PATH="$path_without_wrapper" uname -srmo 2>/dev/null || PATH="$path_without_wrapper" uname -a 2>/dev/null || true)
  fi
  if [ -r /proc/cpuinfo ]; then
    cpu_model=$(awk -F: '/model name|Hardware|Processor/ {gsub(/^ +/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null || true)
  fi
  if PATH="$path_without_wrapper" command -v git >/dev/null 2>&1 && PATH="$path_without_wrapper" git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_commit=$(PATH="$path_without_wrapper" git -C "$repo_root" rev-parse HEAD 2>/dev/null || true)
    git_branch=$(PATH="$path_without_wrapper" git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -n "$(PATH="$path_without_wrapper" git -C "$repo_root" status --porcelain 2>/dev/null || true)" ]; then
      git_dirty="true"
    else
      git_dirty="false"
    fi
  fi
  if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
    scheduler_kind="slurm"
  elif [ -n "${PBS_JOBID:-}" ]; then
    scheduler_kind="pbs"
  elif [ -n "${JACAMAR_CI:-}" ] || [ -n "${JACAMAR_SCHEDULER_ACTION:-}" ]; then
    scheduler_kind="jacamar"
  fi

  commands_json=$(fallback_commands_json)
  environment_json=$(fallback_environment_json)

  cat > "$snapshot_file" <<EOF
{
  "schema_version": 1,
  "stage": $(json_string "$stage"),
  "collected_at": $(json_string "$collected_at"),
  "system": {
    "name": $(json_string "${BK_SYSTEM:-}"),
    "allocation_project_id": $(json_string "${BK_ALLOCATION_PROJECT_ID:-}"),
    "host": {
      "hostname": $(json_string "$hostname_value"),
      "uname": $(json_string "$uname_value"),
      "cpu_model": $(json_string "$cpu_model")
    }
  },
  "scheduler": {
    "kind": $(json_string "$scheduler_kind"),
    "slurm_job_id": $(json_string "${SLURM_JOB_ID:-${SLURM_JOBID:-}}"),
    "slurm_partition": $(json_string "${SLURM_JOB_PARTITION:-}"),
    "pbs_jobid": $(json_string "${PBS_JOBID:-}"),
    "jacamar_scheduler_action": $(json_string "${JACAMAR_SCHEDULER_ACTION:-}")
  },
  "runner": {
    "description": $(json_string "${CI_RUNNER_DESCRIPTION:-}"),
    "id": $(json_string "${CI_RUNNER_ID:-}"),
    "tags": $(json_string "${CI_RUNNER_TAGS:-}")
  },
  "ci": {
    "server_url": $(json_string "${CI_SERVER_URL:-}"),
    "project_path": $(json_string "${CI_PROJECT_PATH:-}"),
    "pipeline_id": $(json_string "${CI_PIPELINE_ID:-}"),
    "job_id": $(json_string "${CI_JOB_ID:-}"),
    "job_name": $(json_string "${CI_JOB_NAME:-}"),
    "commit_ref_name": $(json_string "${CI_COMMIT_REF_NAME:-}"),
    "commit_sha": $(json_string "${CI_COMMIT_SHA:-}")
  },
  "benchkit": {
    "branch": $(json_string "$git_branch"),
    "commit_hash": $(json_string "$git_commit"),
    "dirty": $(json_string "$git_dirty")
  },
  "toolchain": {
    "gcc": $(json_string "$(fallback_command_version gcc)"),
    "mpicc": $(json_string "$(fallback_command_version mpicc)"),
    "nvcc": $(json_string "$(fallback_command_version nvcc)"),
    "python3": $(json_string "$(fallback_command_version python3)"),
    "modules": [],
    "commands": $commands_json,
    "environment": $environment_json,
    "container": {
      "image_path": $(json_string "${BK_SOURCE_CONTAINER_PATH:-}"),
      "image_sha256sum": $(json_string "${BK_SOURCE_CONTAINER_SHA256:-}")
    }
  }
}
EOF
}

if [ "${BK_BUILD_TOOL_WRAPPER_SNAPSHOT:-true}" != "false" ]; then
  snapshot_file="${BK_BUILD_ENVIRONMENT_SNAPSHOT_FILE:-${repo_root}/results/environment_snapshot_build_actual.json}"
  case "$snapshot_file" in
    /*) ;;
    *) snapshot_file="${repo_root}/${snapshot_file}" ;;
  esac

  collector="${repo_root}/scripts/collect_environment_snapshot.sh"
  mkdir -p "$(dirname "$snapshot_file")"
  snapshot_written=false
  if [ "${BK_BUILD_TOOL_WRAPPER_FORCE_FALLBACK:-false}" != "true" ] \
    && [ -f "$collector" ] \
    && PATH="$path_without_wrapper" command -v jq >/dev/null 2>&1; then
    if ! (
      cd "$repo_root" &&
      PATH="$path_without_wrapper" \
        BK_SYSTEM="${BK_SYSTEM:-}" \
        BK_SNAPSHOT_STAGE="${BK_SNAPSHOT_STAGE:-build_actual}" \
        bash "$collector" "$snapshot_file"
    ); then
      echo "bk_build_tool_wrapper: failed to write ${snapshot_file}" >&2
    else
      snapshot_written=true
    fi
  fi
  if [ "$snapshot_written" != true ]; then
    if write_fallback_snapshot "$snapshot_file"; then
      snapshot_written=true
    else
      echo "bk_build_tool_wrapper: failed to write fallback ${snapshot_file}" >&2
    fi
  fi
  if [ "$snapshot_written" != true ] && [ "${BK_STRICT_BUILD_ENVIRONMENT_SNAPSHOT:-false}" = "true" ]; then
    echo "bk_build_tool_wrapper: cannot collect build environment snapshot" >&2
    exit 1
  fi
fi

exec "$real_tool" "$@"

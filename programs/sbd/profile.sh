#!/bin/bash

sbd_ncu_profile_enabled() {
  if [ -z "${BK_SBD_NCU_PROFILE:-}" ]; then
    return 1
  fi
  bk_bool_enabled "$BK_SBD_NCU_PROFILE"
}

sbd_ncu_profile_mode() {
  printf '%s\n' "${BK_SBD_NCU_PROFILE_MODE:-discovery}"
}

sbd_ncu_profile_timeout_seconds() {
  local timeout_seconds="${BK_SBD_NCU_PROFILE_TIMEOUT_SECONDS:-0}"

  case "$timeout_seconds" in
    ''|*[!0-9]*)
      echo "SBD NCU profile timeout must be a non-negative integer: ${timeout_seconds}" >&2
      return 1
      ;;
  esac

  printf '%s\n' "$timeout_seconds"
}



sbd_supports_ncu_profile() {
  case "$1" in
    RIKYU|RC_DGXSP|RC_GH200) return 0 ;;
    *) return 1 ;;
  esac
}

sbd_configure_ncu_profile_from_run_env() {
  local system_name="$1"
  local profiler_tool
  local profiler_level
  local default_profiler_level="detailed"

  if ! sbd_supports_ncu_profile "$system_name"; then
    return 0
  fi

  profiler_tool=$(bk_resolve_profiler_tool ncu SBD_PROFILER_TOOL) || return 1
  if [ -z "$profiler_tool" ]; then
    if [ -z "${BK_SBD_NCU_PROFILE:-}" ]; then
      export BK_SBD_NCU_PROFILE=false
    fi
    return 0
  fi
  if [ "$profiler_tool" != "ncu" ]; then
    echo "SBD ${system_name}: only ncu is supported for separate profile acquisition." >&2
    return 1
  fi

  if [ -z "${BK_SBD_NCU_PROFILE:-}" ]; then
    export BK_SBD_NCU_PROFILE=true
  fi
  if [ "$system_name" = "RIKYU" ]; then
    default_profiler_level="single"
    if [ -z "${BK_SBD_NCU_PLAN_TOP_K:-}" ]; then
      export BK_SBD_NCU_PLAN_TOP_K=1
    fi
    if [ -z "${BK_SBD_NCU_PLAN_LAUNCH_COUNT:-}" ]; then
      export BK_SBD_NCU_PLAN_LAUNCH_COUNT=1
    fi
    if [ -z "${BK_SBD_NCU_PROFILE_TIMEOUT_SECONDS:-}" ]; then
      export BK_SBD_NCU_PROFILE_TIMEOUT_SECONDS=1800
    fi
  fi
  if [ -z "${BK_SBD_NCU_PROFILER_LEVEL:-}" ]; then
    profiler_level=$(bk_resolve_profiler_level "$default_profiler_level" SBD_PROFILER_LEVEL)
    export BK_SBD_NCU_PROFILER_LEVEL="$profiler_level"
  fi
}

sbd_profile_command() {
  local -n prefix_ref="$1" application_ref="$2" command_ref="$3"
  # Nameref output is consumed by the common acquisition helper.
  # shellcheck disable=SC2034
  command_ref=(
    mpirun -np "$n_ranks" bash -lc '
      rank=${OMPI_COMM_WORLD_RANK:-${PMIX_RANK:-${SLURM_PROCID:-0}}}
      local_rank=${OMPI_COMM_WORLD_LOCAL_RANK:-${SLURM_LOCALID:-0}}
      export CUDA_VISIBLE_DEVICES="$local_rank"
      count=$1; shift
      prefix=()
      for ((i=0; i<count; i++)); do prefix+=("$1"); shift; done
      if [ "$rank" = 0 ]; then exec "${prefix[@]}" "$@"; fi
      exec "$@"
    ' bash "${#prefix_ref[@]}" "${prefix_ref[@]}" "${application_ref[@]}"
  )
}

sbd_generate_ncu_plan() {
  local n_ranks="$1" top_k="${BK_SBD_NCU_PLAN_TOP_K:-}"
  shift
  if [ -z "$top_k" ]; then
    case "$(sbd_ncu_profile_mode)" in
      discovery-only|auto-discovery-only) top_k=0 ;;
      *) top_k=3 ;;
    esac
  fi
  bk_discover_ncu_plan --section mult --command-builder sbd_profile_command \
    --csv "${BK_SBD_NCU_DISCOVERY_CSV:-${BK_SBD_NSYS_KERNEL_SUMMARY_CSV:-}}" \
    --top-k "$top_k" \
    --min-total-time-pct "${BK_SBD_NCU_PLAN_MIN_TOTAL_TIME_PCT:-0}" \
    --min-instances "${BK_SBD_NCU_PLAN_MIN_INSTANCES:-1}" \
    --launch-count "${BK_SBD_NCU_PLAN_LAUNCH_COUNT:-10}" \
    --warmup-fraction "${BK_SBD_NCU_PLAN_WARMUP_FRACTION:-0}" \
    --max-launch-skip "${BK_SBD_NCU_PLAN_MAX_LAUNCH_SKIP:-1}" \
    --metric-set "${BK_SBD_NCU_PLAN_METRIC_SET:-gpu_kernel_estimation}" -- ./diag "$@"
}

sbd_profile_section_name_from_kernel() {
  local kernel_name="$1"

  case "$kernel_name" in
    *Mult*|*mult*|*gemm*|*GEMM*)
      printf '%s\n' "mult"
      ;;
    *)
      printf '%s\n' "mult"
      ;;
  esac
}

sbd_run_rank0_ncu_profile() {
  local n_ranks="$1" profile_name="$2" profile_slug="$3" kernel_regex="$4"
  local launch_skip="$5" launch_count="$6" profiler_level="$7" section_name="$8"
  local plan_file="${9:-}" timeout_seconds
  shift 9
  timeout_seconds=$(sbd_ncu_profile_timeout_seconds) || return 1
  bk_acquire_ncu --profile-name "$profile_name" --profile-slug "$profile_slug" \
    --kernel-regex "$kernel_regex" --launch-skip "$launch_skip" --launch-count "$launch_count" \
    --level "$profiler_level" --section "$section_name" --plan "$plan_file" \
    --timeout "$timeout_seconds" --command-builder sbd_profile_command -- ./diag "$@"
}

sbd_run_ncu_plan_profiles() {
  local plan_json="$1"
  local n_ranks="$2"
  shift 2
  local profiler_level="${BK_SBD_NCU_PROFILER_LEVEL:-${BK_PROFILER_LEVEL:-detailed}}"
  local profile_name
  local section_name
  local kernel_regex
  local launch_skip
  local launch_count
  local kernel_name
  local profile_slug
  local profile_seen=0

  while IFS=$'\t' read -r profile_name section_name kernel_regex launch_skip launch_count kernel_name; do
    if [ -z "$profile_name" ] || [ -z "$kernel_regex" ]; then
      continue
    fi
    if [ "$section_name" = "-" ] || [ -z "$section_name" ]; then
      section_name=$(sbd_profile_section_name_from_kernel "$kernel_name")
    fi
    profile_slug=$(bk_profile_slug "$profile_name")
    profile_seen=$((profile_seen + 1))
    sbd_run_rank0_ncu_profile "$n_ranks" "$profile_name" "$profile_slug" \
      "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" \
      "$section_name" "$plan_json" "$@" || return $?
  done < <(bk_ncu_plan_profiles "$plan_json")

  if [ "$profile_seen" -eq 0 ]; then
    echo "SBD NCU plan has no executable profiles: ${plan_json}" >&2
    return 1
  fi
}

sbd_run_optional_ncu_profiles() {
  local system_name="$1"
  local n_ranks="$2"
  local profile_status
  shift 2

  if ! sbd_ncu_profile_enabled; then
    return 0
  fi

  profile_status=0
  sbd_run_configured_ncu_profiles "$system_name" "$n_ranks" "$@" || profile_status=$?
  if [ "$profile_status" -ne 0 ]; then
    echo "SBD NCU profile acquisition failed with status ${profile_status}; continuing with benchmark result." >&2
  fi
  return 0
}

sbd_run_configured_ncu_profiles() {
  local system_name="$1"
  local n_ranks="$2"
  shift 2
  local plan_json

  if ! sbd_ncu_profile_enabled; then
    return 0
  fi

  case "$system_name" in
    RIKYU|RC_DGXSP|RC_GH200) ;;
    *)
      echo "SBD NCU profile acquisition is only supported for GPU SBD systems." >&2
      return 1
      ;;
  esac

  case "$(sbd_ncu_profile_mode)" in
    discovery|auto)
      plan_json=$(sbd_generate_ncu_plan "$n_ranks" "$@") || return 1
      sbd_run_ncu_plan_profiles "$plan_json" "$n_ranks" "$@" || return $?
      ;;
    discovery-only|auto-discovery-only)
      sbd_generate_ncu_plan "$n_ranks" "$@" >/dev/null || return $?
      echo "SBD: completed NSYS kernel discovery; skipping NCU profile execution." >&2
      ;;
    *)
      echo "SBD: unsupported BK_SBD_NCU_PROFILE_MODE='$(sbd_ncu_profile_mode)'." >&2
      echo "Use discovery or discovery-only." >&2
      return 1
      ;;
  esac
}

#!/bin/bash

: "${SBD_BENCHKIT_ROOT:=$PWD}"

sbd_ncu_profile_enabled() {
  if [ -z "${BK_SBD_NCU_PROFILE:-}" ]; then
    return 1
  fi
  bk_bool_enabled "$BK_SBD_NCU_PROFILE"
}

sbd_ncu_profile_mode() {
  printf '%s\n' "${BK_SBD_NCU_PROFILE_MODE:-discovery}"
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
  if [ -z "${BK_SBD_NCU_PROFILER_LEVEL:-}" ]; then
    profiler_level=$(bk_resolve_profiler_level detailed SBD_PROFILER_LEVEL)
    export BK_SBD_NCU_PROFILER_LEVEL="$profiler_level"
  fi
}

sbd_profile_results_dir() {
  printf '%s\n' "${RESULTS_DIR:-${SBD_BENCHKIT_ROOT}/results}"
}

sbd_register_mult_section_artifact() {
  local artifact_path="$1"

  if [ -z "${SBD_MULT_SECTION_ARTIFACTS:-}" ]; then
    SBD_MULT_SECTION_ARTIFACTS="$artifact_path"
  else
    SBD_MULT_SECTION_ARTIFACTS="${SBD_MULT_SECTION_ARTIFACTS},${artifact_path}"
  fi
  export SBD_MULT_SECTION_ARTIFACTS
}

sbd_run_rank0_nsys_discovery() {
  local n_ranks="$1"
  local report_base="$2"
  local log_file="$3"
  shift 3
  local profile_status

  echo "Running SBD NSYS kernel discovery for automatic NCU plan generation" >&2
  set +e
  mpirun -np "$n_ranks" bash -lc '
    rank=${OMPI_COMM_WORLD_RANK:-${PMIX_RANK:-${SLURM_PROCID:-0}}}
    local_rank=${OMPI_COMM_WORLD_LOCAL_RANK:-${SLURM_LOCALID:-0}}
    export CUDA_VISIBLE_DEVICES="${local_rank}"
    report_base="$1"
    shift
    if [ "$rank" = 0 ]; then
      exec nsys profile --force-overwrite=true --trace=cuda --sample=none -o "$report_base" ./diag "$@"
    fi
    exec ./diag "$@"
  ' bash "$report_base" "$@" > "$log_file" 2>&1
  profile_status=$?
  set -e

  if [ "$profile_status" -ne 0 ]; then
    echo "SBD NSYS kernel discovery failed with status ${profile_status}" >&2
    return "$profile_status"
  fi
}

sbd_find_generated_nsys_kernel_csv() {
  local results_dir="$1"
  local found=""

  while IFS= read -r candidate; do
    found="$candidate"
    break
  done < <(find "$results_dir" -maxdepth 1 -type f \
    \( -name 'sbd_nsys_stats*cuda_gpu_kern_sum*.csv' -o -name 'sbd_nsys_cuda_gpu_kern_sum*.csv' \) \
    | sort)

  printf '%s\n' "$found"
}

sbd_generate_ncu_plan() {
  local n_ranks="$1"
  shift
  local results_dir
  local python_bin="${PYTHON_BIN:-python3}"
  local discovery_csv="${BK_SBD_NCU_DISCOVERY_CSV:-${BK_SBD_NSYS_KERNEL_SUMMARY_CSV:-}}"
  local discovery_json
  local plan_json
  local nsys_base
  local nsys_report
  local nsys_stats_base
  local nsys_log
  local generated_csv
  local nsys_stats_status
  local plan_top_k="${BK_SBD_NCU_PLAN_TOP_K:-}"
  local mode

  results_dir=$(sbd_profile_results_dir)
  discovery_json="${results_dir}/sbd_kernel_discovery.json"
  plan_json="${results_dir}/sbd_ncu_plan.json"
  nsys_base="${results_dir}/sbd_nsys_kernel_discovery"
  nsys_report="${nsys_base}.nsys-rep"
  nsys_stats_base="${results_dir}/sbd_nsys_stats"
  nsys_log="${results_dir}/log_sbd_nsys_discovery.txt"
  mode=$(sbd_ncu_profile_mode)

  if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo "SBD NCU discovery requires ${python_bin} for plan generation." >&2
    return 1
  fi

  if [ -z "$discovery_csv" ]; then
    if ! command -v nsys >/dev/null 2>&1; then
      echo "SBD NCU discovery requires nsys, or set BK_SBD_NCU_DISCOVERY_CSV to an existing cuda_gpu_kern_sum CSV." >&2
      return 1
    fi

    rm -f "$nsys_report" "${nsys_base}.sqlite" "${nsys_stats_base}"*
    sbd_run_rank0_nsys_discovery "$n_ranks" "$nsys_base" "$nsys_log" "$@" || return $?
    if [ ! -f "$nsys_report" ]; then
      echo "SBD NSYS report was not created: ${nsys_report}" >&2
      return 1
    fi

    set +e
    nsys stats --force-export=true \
      --report cuda_gpu_kern_sum,cuda_api_sum \
      --format csv \
      --output "$nsys_stats_base" \
      "$nsys_report" >/dev/null
    nsys_stats_status=$?
    set -e
    if [ "$nsys_stats_status" -ne 0 ]; then
      echo "SBD NSYS CUDA summary export failed with status ${nsys_stats_status}" >&2
      return "$nsys_stats_status"
    fi

    generated_csv=$(sbd_find_generated_nsys_kernel_csv "$results_dir")
    discovery_csv="${generated_csv:-${nsys_stats_base}_cuda_gpu_kern_sum.csv}"
    if [ ! -s "$discovery_csv" ]; then
      echo "SBD NSYS CUDA kernel summary CSV is missing or empty: ${discovery_csv}" >&2
      return 1
    fi
    echo "SBD NSYS CUDA kernel summary CSV: ${discovery_csv}" >&2
  fi

  if [ ! -s "$discovery_csv" ]; then
    echo "SBD NCU discovery CSV does not exist or is empty: ${discovery_csv}" >&2
    return 1
  fi

  if [ -z "$plan_top_k" ]; then
    case "$mode" in
      discovery-only|auto-discovery-only)
        plan_top_k=0
        ;;
      *)
        plan_top_k=3
        ;;
    esac
  fi

  if ! "$python_bin" "${SBD_BENCHKIT_ROOT}/scripts/profiling/generate_ncu_plan.py" \
    --nsys-csv "$discovery_csv" \
    --out-discovery "$discovery_json" \
    --out-plan "$plan_json" \
    --top-k "$plan_top_k" \
    --min-total-time-pct "${BK_SBD_NCU_PLAN_MIN_TOTAL_TIME_PCT:-0}" \
    --min-instances "${BK_SBD_NCU_PLAN_MIN_INSTANCES:-1}" \
    --launch-count "${BK_SBD_NCU_PLAN_LAUNCH_COUNT:-10}" \
    --warmup-fraction "${BK_SBD_NCU_PLAN_WARMUP_FRACTION:-0}" \
    --max-launch-skip "${BK_SBD_NCU_PLAN_MAX_LAUNCH_SKIP:-1}" \
    --metric-set "${BK_SBD_NCU_PLAN_METRIC_SET:-gpu_kernel_estimation}"; then
    echo "SBD NCU plan generation failed." >&2
    return 1
  fi

  if [ ! -s "$discovery_json" ] || [ ! -s "$plan_json" ]; then
    echo "SBD NCU discovery or plan JSON was not created." >&2
    return 1
  fi

  echo "SBD kernel discovery JSON: ${discovery_json}" >&2
  echo "SBD NCU plan JSON: ${plan_json}" >&2
  printf '%s\n' "$plan_json"
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
  local n_ranks="$1"
  local profile_name="$2"
  local profile_slug="$3"
  local kernel_regex="$4"
  local launch_skip="$5"
  local launch_count="$6"
  local profiler_level="$7"
  local section_name="$8"
  local discovery_metadata_json="${9:-"{}"}"
  shift 9

  local results_dir
  local archive_path
  local archive_rel_path
  local metadata_path
  local metadata_rel_path
  local raw_dir
  local profile_log
  local stage_dir="${BK_PROFILER_STAGE_DIR:-bk_profiler_artifact}"
  local rep_name="rep1"
  local rep_dir
  local profile_base
  local ncu_level_arg_text
  local ncu_level_args=()
  local report_file
  local profiler_status
  local archive_status

  results_dir=$(sbd_profile_results_dir)
  archive_path="${results_dir}/padata_${profile_slug}.tgz"
  archive_rel_path="results/padata_${profile_slug}.tgz"
  metadata_path="${archive_path%.tgz}.metadata.json"
  metadata_rel_path="${archive_rel_path%.tgz}.metadata.json"
  raw_dir="ncu_${profile_slug}"
  profile_log="${results_dir}/log_sbd_ncu_${profile_slug}.txt"
  rep_dir="${raw_dir}/${rep_name}"
  profile_base="${rep_dir}/profile"

  if ! command -v ncu >/dev/null 2>&1; then
    echo "SBD NCU profile requested but ncu is not in PATH." >&2
    return 1
  fi

  ncu_level_arg_text=$(bk_profiler_ncu_level_args "$profiler_level") || return 1
  read -r -a ncu_level_args <<< "$ncu_level_arg_text"

  rm -rf "$raw_dir" "$stage_dir"
  mkdir -p "$rep_dir" "$stage_dir/raw" "$stage_dir/reports"

  echo "SBD NCU profile: profile='${profile_name}' kernel='${kernel_regex}' skip=${launch_skip} count=${launch_count}" >&2
  echo "bk_profiler[ncu]: starting ${rep_name} level=${profiler_level} on rank 0" >&2
  set +e
  mpirun -np "$n_ranks" bash -lc '
    rank=${OMPI_COMM_WORLD_RANK:-${PMIX_RANK:-${SLURM_PROCID:-0}}}
    local_rank=${OMPI_COMM_WORLD_LOCAL_RANK:-${SLURM_LOCALID:-0}}
    export CUDA_VISIBLE_DEVICES="${local_rank}"
    profile_base="$1"
    level_argc="$2"
    shift 2
    level_args=()
    i=0
    while [ "$i" -lt "$level_argc" ]; do
      level_args+=("$1")
      shift
      i=$((i + 1))
    done
    kernel_regex="$1"
    launch_skip="$2"
    launch_count="$3"
    shift 3
    if [ "$rank" = 0 ]; then
      exec ncu -o "$profile_base" --target-processes all "${level_args[@]}" \
        --kernel-name-base demangled --kernel-name "$kernel_regex" \
        --launch-skip "$launch_skip" --launch-count "$launch_count" ./diag "$@"
    fi
    exec ./diag "$@"
  ' bash "$profile_base" "${#ncu_level_args[@]}" "${ncu_level_args[@]}" \
    "$kernel_regex" "$launch_skip" "$launch_count" "$@" > "$profile_log" 2>&1
  profiler_status=$?
  set -e

  if [ "$profiler_status" -eq 0 ]; then
    echo "bk_profiler[ncu]: completed ${rep_name} level=${profiler_level}" >&2
  else
    echo "bk_profiler[ncu]: failed ${rep_name} level=${profiler_level} status=${profiler_status}" >&2
  fi

  report_file=$(bk_profiler_find_ncu_report "$rep_dir" || true)
  if [ -n "$report_file" ]; then
    ncu --import "$report_file" \
      --page raw \
      --csv \
      --print-units base \
      --print-fp > "${rep_dir}/profile_raw.csv" 2> "${rep_dir}/profile_raw.csv.log" || true
    ncu --import "$report_file" --page details > "$stage_dir/reports/ncu_import_${rep_name}.txt" 2>&1 || true
  fi

  cp -R "$rep_dir" "$stage_dir/raw/${rep_name}"
  case "${BK_PROFILER_ARCHIVE_NCU_REPORT:-false}" in
    1|true|TRUE|yes|YES|on|ON) ;;
    *)
      find "$stage_dir/raw/${rep_name}" -maxdepth 1 -type f \( \
        -name '*.ncu-rep' -o \
        -name '*.nsight-cuprof' \
      \) -delete
      ;;
  esac
  bk_profiler_write_meta "$stage_dir" ncu "$profiler_level" both "$rep_name" "$profiler_level" \
    "--kernel-name-base demangled --kernel-name ${kernel_regex} --launch-skip ${launch_skip} --launch-count ${launch_count}" ""

  if tar -czf "$archive_path" "$stage_dir"; then
    archive_status=0
  else
    archive_status=$?
  fi
  rm -rf "$stage_dir"

  if [ "$archive_status" -ne 0 ]; then
    return "$archive_status"
  fi
  if [ "$profiler_status" -ne 0 ]; then
    echo "SBD NCU profile '${profile_name}' failed with status ${profiler_status}" >&2
    return "$profiler_status"
  fi

  bk_write_gpu_kernel_profile_metadata \
    "$metadata_path" \
    "$archive_rel_path" \
    "$section_name" \
    "$profile_name" \
    "$profile_slug" \
    "$kernel_regex" \
    "$launch_skip" \
    "$launch_count" \
    "$discovery_metadata_json" || return $?

  echo "SBD NCU profile metadata: ${metadata_rel_path}" >&2
  sbd_register_mult_section_artifact "$archive_rel_path"
}

sbd_run_ncu_plan_profiles() {
  local plan_json="$1"
  local n_ranks="$2"
  shift 2
  local python_bin="${PYTHON_BIN:-python3}"
  local profiler_level="${BK_SBD_NCU_PROFILER_LEVEL:-${BK_PROFILER_LEVEL:-detailed}}"
  local profile_name
  local section_name
  local kernel_regex
  local launch_skip
  local launch_count
  local kernel_name
  local profile_slug
  local profile_seen=0
  local discovery_metadata_json

  while IFS=$'\t' read -r profile_name section_name kernel_regex launch_skip launch_count kernel_name; do
    if [ -z "$profile_name" ] || [ -z "$kernel_regex" ]; then
      continue
    fi
    if [ "$section_name" = "-" ] || [ -z "$section_name" ]; then
      section_name=$(sbd_profile_section_name_from_kernel "$kernel_name")
    fi
    profile_slug=$(bk_profile_slug "$profile_name")
    profile_seen=$((profile_seen + 1))
    discovery_metadata_json=$("$python_bin" - "$plan_json" "$profile_name" "$section_name" <<'PY'
import json
import sys

plan_path, profile_name, section_name = sys.argv[1:4]
with open(plan_path, encoding="utf-8") as handle:
    plan = json.load(handle)
for profile in plan.get("profiles", []):
    if profile.get("name") == profile_name:
        discovery = dict(profile.get("selection") or {})
        discovery.update({
            "section": section_name,
            "kernel_name": profile.get("kernel_name"),
            "kernel_match": profile.get("kernel_match"),
            "profile_name": profile.get("name"),
            "launch_skip": profile.get("launch_skip"),
            "launch_count": profile.get("launch_count"),
            "metric_set": profile.get("metric_set"),
        })
        print(json.dumps(discovery, separators=(",", ":")))
        break
else:
    print("{}")
PY
)
    sbd_run_rank0_ncu_profile "$n_ranks" "$profile_name" "$profile_slug" \
      "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" \
      "$section_name" "$discovery_metadata_json" "$@" || return $?
  done < <("$python_bin" "${SBD_BENCHKIT_ROOT}/scripts/profiling/iter_ncu_plan_profiles.py" --plan "$plan_json")

  if [ "$profile_seen" -eq 0 ]; then
    echo "SBD NCU plan has no executable profiles: ${plan_json}" >&2
    return 1
  fi
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

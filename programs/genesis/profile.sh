#!/bin/bash

genesis_ncu_profile_enabled() {
    if [ -n "${BK_GENESIS_NCU_PROFILE:-}" ]; then
        bk_bool_enabled "$BK_GENESIS_NCU_PROFILE"
        return $?
    fi

    # GH200-class GENESIS runs always keep the unprofiled application run for
    # FOM/section timing, then collect extra NCU windows for GPU-kernel ratios.
    return 0
}

genesis_find_apptainer_payload_index() {
    local cmd_name="$1"
    local -n cmd_ref="$cmd_name"
    local idx=0
    local apptainer_idx=-1
    local arg

    GENESIS_APPTAINER_INDEX=-1
    GENESIS_APPTAINER_PAYLOAD_INDEX=-1

    for idx in "${!cmd_ref[@]}"; do
        case "${cmd_ref[$idx]}" in
          apptainer|*/apptainer|singularity|*/singularity)
            apptainer_idx="$idx"
            break
            ;;
        esac
    done
    if [ "$apptainer_idx" -lt 0 ]; then
        return 1
    fi

    idx=$((apptainer_idx + 1))
    if [ "${cmd_ref[$idx]:-}" = "exec" ]; then
        idx=$((idx + 1))
    fi

    while [ "$idx" -lt "${#cmd_ref[@]}" ]; do
        arg="${cmd_ref[$idx]}"
        case "$arg" in
          --)
            idx=$((idx + 1))
            break
            ;;
          --bind|--mount|--env|--env-file|--pwd|--cwd|--home|--workdir|-B|-H|-W)
            idx=$((idx + 2))
            ;;
          --bind=*|--mount=*|--env=*|--env-file=*|--pwd=*|--cwd=*|--home=*|--workdir=*)
            idx=$((idx + 1))
            ;;
          --nv|--nvccli|--rocm|--cleanenv|--contain|--containall|--no-home|--no-pid|--no-umask|--no-mount|--writable-tmpfs|--sharens)
            idx=$((idx + 1))
            ;;
          -*)
            idx=$((idx + 1))
            ;;
          *)
            GENESIS_APPTAINER_INDEX="$apptainer_idx"
            GENESIS_APPTAINER_PAYLOAD_INDEX=$((idx + 1))
            return 0
            ;;
        esac
    done

    return 1
}

genesis_build_container_rank0_profile_command() {
    local profile_name="$1"
    local app_name="$2"
    local out_name="$3"
    local -n profile_ref="$profile_name"
    local -n app_ref="$app_name"
    local -n out_ref="$out_name"
    local payload_index
    local profile_argc

    genesis_find_apptainer_payload_index "$app_name" || return 1
    payload_index="$GENESIS_APPTAINER_PAYLOAD_INDEX"
    profile_argc="${#profile_ref[@]}"

    out_ref=(
        "${app_ref[@]:0:$payload_index}"
        bash -lc
        'rank=${SLURM_PROCID:-${PMIX_RANK:-${OMPI_COMM_WORLD_RANK:-0}}}; profile_argc=$1; shift; profile_cmd=(); i=0; while [ "$i" -lt "$profile_argc" ]; do profile_cmd+=("$1"); shift; i=$((i + 1)); done; if [ "$rank" = 0 ]; then exec "${profile_cmd[@]}"; fi; exec "$@"'
        bash
        "$profile_argc"
        "${profile_ref[@]}"
        "${app_ref[@]:$payload_index}"
    )
}

genesis_build_container_once_command() {
    local app_name="$1"
    local out_name="$2"
    shift 2
    local -n app_ref="$app_name"
    # Nameref output is consumed by the caller.
    # shellcheck disable=SC2178
    local -n out_ref="$out_name"
    local prefix_len

    genesis_find_apptainer_payload_index "$app_name" || return 1
    prefix_len=$((GENESIS_APPTAINER_PAYLOAD_INDEX - GENESIS_APPTAINER_INDEX))
    # shellcheck disable=SC2034
    out_ref=(
        "${app_ref[@]:$GENESIS_APPTAINER_INDEX:$prefix_len}"
        "$@"
    )
}

genesis_configure_ncu_profile() {
    local system_name="$1"
    local profiler_tool_var="$2"
    local profiler_level_var="$3"
    local module_var="$4"
    local profiler_default="none"
    local profiler_requested
    local profiler_tool
    local profiler_level_default="single"

    GENESIS_NCU_PROFILE_ENABLED=0
    GENESIS_NCU_PROFILER_LEVEL=""

    if genesis_ncu_profile_enabled; then
        profiler_default="ncu"
        profiler_level_default="detailed"
    fi

    profiler_requested=$(bk_resolve_profiler_tool "$profiler_default" "$profiler_tool_var" GENESIS_PROFILER_TOOL) || return 1
    profiler_tool=$(bk_get_profiler_tool "$profiler_requested") || return 1
    GENESIS_NCU_PROFILER_LEVEL=$(bk_resolve_profiler_level "$profiler_level_default" "$profiler_level_var" GENESIS_PROFILER_LEVEL)

    if [ -z "$profiler_tool" ]; then
        return 0
    fi

    if [ "$profiler_tool" != "ncu" ]; then
        echo "Genesis ${system_name}: only ncu is supported for separate GENESIS GPU profile acquisition." >&2
        return 1
    fi

    if ! command -v ncu >/dev/null 2>&1 && [ "$system_name" = "RIKYU" ]; then
        echo "Genesis ${system_name}: host ncu is not in PATH; profiler commands will run inside the Apptainer container." >&2
    elif ! command -v ncu >/dev/null 2>&1; then
        echo "Genesis ${system_name}: ncu profiler requested but ncu is not in PATH." >&2
        echo "Load Nsight Compute with ${module_var}, or set ${profiler_tool_var}=none / GENESIS_PROFILER_TOOL=none / BK_PROFILER=none to run without profiling." >&2
        return 1
    fi

    GENESIS_NCU_PROFILE_ENABLED=1
}

genesis_ncu_profile_names() {
    if [ -n "${BK_GENESIS_NCU_PROFILE_NAMES:-}" ]; then
        printf '%s\n' "$BK_GENESIS_NCU_PROFILE_NAMES" | tr ',;' '  '
    elif [ -n "${BK_GENESIS_NCU_KERNEL_REGEX:-}" ]; then
        printf '%s\n' "custom"
    else
        printf '%s\n' "inter intra pairlist"
    fi
}

genesis_default_ncu_kernel_regex() {
    case "$1" in
      inter)
        printf '%s\n' 'regex:.*force_inter_cell.*'
        ;;
      intra)
        printf '%s\n' 'regex:.*force_intra_cell.*'
        ;;
      pairlist)
        printf '%s\n' 'regex:.*build_pairlist.*'
        ;;
      custom)
        printf '%s\n' "${BK_GENESIS_NCU_KERNEL_REGEX:-}"
        ;;
    esac
}

genesis_default_ncu_launch_skip() {
    case "$1" in
      pairlist)
        printf '%s\n' "${BK_GENESIS_NCU_LAUNCH_SKIP_PAIRLIST:-${BK_GENESIS_NCU_PAIRLIST_LAUNCH_SKIP:-10}}"
        ;;
      *)
        printf '%s\n' "${BK_GENESIS_NCU_LAUNCH_SKIP:-100}"
        ;;
    esac
}

genesis_default_ncu_launch_count() {
    case "$1" in
      pairlist)
        printf '%s\n' "${BK_GENESIS_NCU_LAUNCH_COUNT_PAIRLIST:-${BK_GENESIS_NCU_PAIRLIST_LAUNCH_COUNT:-10}}"
        ;;
      *)
        printf '%s\n' "${BK_GENESIS_NCU_LAUNCH_COUNT:-10}"
        ;;
    esac
}

genesis_profile_section_name() {
    case "$1" in
      inter)
        printf '%s\n' "pme_real_inter"
        ;;
      intra)
        printf '%s\n' "pme_real_intra"
        ;;
      pairlist)
        printf '%s\n' "pairlist"
        ;;
      *)
        printf '%s\n' "$1"
        ;;
    esac
}

genesis_profile_section_name_from_kernel() {
    local kernel_name="$1"
    case "$kernel_name" in
      *build_pairlist*)
        printf '%s\n' "pairlist"
        ;;
      *force_inter_cell*|*inter_cell*)
        printf '%s\n' "pme_real_inter"
        ;;
      *force_intra_cell*|*intra_cell*)
        printf '%s\n' "pme_real_intra"
        ;;
      *)
        printf '%s\n' ""
        ;;
    esac
}



genesis_prepare_ncu_input() {
    local source_input="$1"
    local profile_name="$2"
    local profile_slug="$3"
    local profile_key="$4"
    local nsteps_var="BK_GENESIS_NCU_${profile_key}_NSTEPS"
    local nsteps="${!nsteps_var:-${BK_GENESIS_NCU_NSTEPS:-600}}"
    local target_input

    case "$nsteps" in
      ""|0|none|NONE|off|OFF)
        printf '%s\n' "$source_input"
        return 0
        ;;
    esac

    if [[ ! "$nsteps" =~ ^[0-9]+$ ]]; then
        echo "GENESIS NCU profile '${profile_name}' has invalid nsteps: ${nsteps}" >&2
        echo "Set ${nsteps_var} or BK_GENESIS_NCU_NSTEPS to a positive integer, or off to reuse the benchmark input." >&2
        return 1
    fi

    target_input="${source_input%.sub}.ncu_${profile_slug}.sub"
    awk -v nsteps="$nsteps" '
      {
        if ($0 ~ /(^|[[:space:]])nsteps[[:space:]]*=/) {
          sub(/nsteps[[:space:]]*=[[:space:]]*[0-9]+/, "nsteps          =       " nsteps)
          changed = 1
        }
        print
      }
      END {
        if (!changed) {
          exit 2
        }
      }
    ' "$source_input" > "$target_input" || {
        echo "GENESIS NCU profile '${profile_name}' failed to prepare ${target_input} from ${source_input}" >&2
        echo "The input must contain an nsteps assignment, or set BK_GENESIS_NCU_NSTEPS=off." >&2
        return 1
    }

    echo "Prepared GENESIS NCU profile '${profile_name}' input ${target_input} with nsteps=${nsteps}" >&2
    printf '%s\n' "$target_input"
}

genesis_profile_command() {
    local -n prefix_ref="$1" application_ref="$2" command_ref="$3"
    local profile_payload=()
    if genesis_find_apptainer_payload_index "$2"; then
        # Passed by name to the container command builder.
        # shellcheck disable=SC2034
        profile_payload=("${prefix_ref[@]}" "${application_ref[@]:$GENESIS_APPTAINER_PAYLOAD_INDEX}")
        genesis_build_container_rank0_profile_command profile_payload "$2" "$3"
    else
        command_ref=("${prefix_ref[@]}" "${application_ref[@]}")
    fi
}

genesis_profile_export() {
    if genesis_find_apptainer_payload_index "$1"; then
        genesis_build_container_once_command "$@"
    else
        # Nameref output is consumed by the common acquisition helper.
        # shellcheck disable=SC2178
        local -n command_ref="$2"
        shift 2
        # shellcheck disable=SC2034
        command_ref=("$@")
    fi
}

genesis_run_ncu_profile() {
    local name="$1" slug="$2" kernel="$3" skip="$4" count="$5"
    local level="$6" section="$7" plan_file="${8:-}"
    shift 8
    bk_acquire_ncu --profile-name "$name" --profile-slug "$slug" \
        --kernel-regex "$kernel" --launch-skip "$skip" --launch-count "$count" \
        --level "$level" --section "$section" --plan "$plan_file" \
        --command-builder genesis_profile_command --export-builder genesis_profile_export -- "$@"
}

genesis_run_ncu_profiles() {
    local profiler_level="$1"
    shift
    local profile_names
    local profile_name
    local profile_key
    local profile_slug
    local regex_var
    local skip_var
    local count_var
    local kernel_regex
    local launch_skip
    local launch_count
    local profile_cmd
    local last_index
    local profile_input

    profile_names=$(genesis_ncu_profile_names)
    for profile_name in $profile_names; do
        case "$profile_name" in
          ""|none|NONE|off|OFF)
            continue
            ;;
        esac

        profile_key=$(bk_profile_key "$profile_name")
        profile_slug=$(bk_profile_slug "$profile_name")
        regex_var="BK_GENESIS_NCU_${profile_key}_KERNEL_REGEX"
        skip_var="BK_GENESIS_NCU_${profile_key}_LAUNCH_SKIP"
        count_var="BK_GENESIS_NCU_${profile_key}_LAUNCH_COUNT"

        kernel_regex="${!regex_var:-$(genesis_default_ncu_kernel_regex "$profile_name")}"
        launch_skip="${!skip_var:-$(genesis_default_ncu_launch_skip "$profile_name")}"
        launch_count="${!count_var:-$(genesis_default_ncu_launch_count "$profile_name")}"

        if [ -z "$kernel_regex" ]; then
            echo "GENESIS NCU profile '${profile_name}' has no kernel regex. Set ${regex_var} or BK_GENESIS_NCU_KERNEL_REGEX." >&2
            return 1
        fi

        profile_cmd=("$@")
        last_index=$((${#profile_cmd[@]} - 1))
        if [ "$last_index" -lt 0 ]; then
            echo "GENESIS NCU profile '${profile_name}' has no command to run." >&2
            return 1
        fi
        profile_input=$(genesis_prepare_ncu_input "${profile_cmd[$last_index]}" "$profile_name" "$profile_slug" "$profile_key")
        profile_cmd[$last_index]="$profile_input"

        genesis_run_ncu_profile "$profile_name" "$profile_slug" "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" "$(genesis_profile_section_name "$profile_name")" "" "${profile_cmd[@]}" || return $?
    done
}

genesis_ncu_profile_mode() {
    printf '%s\n' "${BK_GENESIS_NCU_PROFILE_MODE:-${GENESIS_NCU_PROFILE_MODE_DEFAULT:-discovery}}"
}

genesis_generate_ncu_plan() {
    shift # The acquisition plan selects individual NCU windows independently of level.
    local csv="${BK_GENESIS_NCU_DISCOVERY_CSV:-${BK_GENESIS_NSYS_KERNEL_SUMMARY_CSV:-}}"
    local top_k="${BK_GENESIS_NCU_PLAN_TOP_K:-}" last_index
    local discovery_cmd=("$@")
    if [ -z "$csv" ]; then
        last_index=$(("${#discovery_cmd[@]}" - 1))
        [ "$last_index" -ge 0 ] || return 1
        discovery_cmd[$last_index]=$(genesis_prepare_ncu_input "${discovery_cmd[$last_index]}" discovery discovery DISCOVERY) || return 1
    fi
    if [ -z "$top_k" ]; then
        case "$(genesis_ncu_profile_mode)" in
          discovery-only|auto-discovery-only) top_k=0 ;;
          *) top_k=3 ;;
        esac
    fi
    bk_discover_ncu_plan --csv "$csv" --command-builder genesis_profile_command \
        --export-builder genesis_profile_export --top-k "$top_k" \
        --min-total-time-pct "${BK_GENESIS_NCU_PLAN_MIN_TOTAL_TIME_PCT:-0}" \
        --min-instances "${BK_GENESIS_NCU_PLAN_MIN_INSTANCES:-1}" \
        --launch-count "${BK_GENESIS_NCU_PLAN_LAUNCH_COUNT:-${BK_GENESIS_NCU_LAUNCH_COUNT:-10}}" \
        --warmup-fraction "${BK_GENESIS_NCU_PLAN_WARMUP_FRACTION:-0}" \
        --max-launch-skip "${BK_GENESIS_NCU_PLAN_MAX_LAUNCH_SKIP:-1}" \
        --metric-set "${BK_GENESIS_NCU_PLAN_METRIC_SET:-gpu_kernel_estimation}" -- "${discovery_cmd[@]}"
}

genesis_run_ncu_plan_profiles() {
    local plan_json="$1"
    local profiler_level="$2"
    shift 2
    local profile_name
    local section_name
    local kernel_regex
    local launch_skip
    local launch_count
    local profile_slug
    local profile_key
    local profile_cmd
    local last_index
    local profile_input
    local kernel_name
    local profile_seen=0
    local profile_rows=()
    local profile_row
    mapfile -t profile_rows < <(bk_ncu_plan_profiles "$plan_json")
    for profile_row in "${profile_rows[@]}"; do
        IFS=$'\t' read -r profile_name section_name kernel_regex launch_skip launch_count kernel_name <<< "$profile_row"
        if [ -z "$profile_name" ] || [ -z "$kernel_regex" ]; then
            continue
        fi
        if [ "$section_name" = "-" ]; then
            section_name=""
        fi
        if [ -z "$section_name" ]; then
            section_name=$(genesis_profile_section_name_from_kernel "$kernel_name")
        fi
        profile_seen=$((profile_seen + 1))
        profile_slug=$(bk_profile_slug "$profile_name")
        profile_key=$(bk_profile_key "$profile_name")
        profile_cmd=("$@")
        last_index=$((${#profile_cmd[@]} - 1))
        if [ "$last_index" -lt 0 ]; then
            echo "GENESIS NCU plan profile '${profile_name}' has no command to run." >&2
            return 1
        fi
        profile_input=$(genesis_prepare_ncu_input "${profile_cmd[$last_index]}" "$profile_name" "$profile_slug" "$profile_key")
        profile_cmd[$last_index]="$profile_input"
        genesis_run_ncu_profile "$profile_name" "$profile_slug" "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" "$section_name" "$plan_json" "${profile_cmd[@]}" || return $?
    done
    if [ "$profile_seen" -eq 0 ]; then
        echo "GENESIS NCU plan has no executable profiles: ${plan_json}" >&2
        return 1
    fi
}

genesis_run_configured_ncu_profiles() {
    local system_name="$1"
    shift
    local profiler_level="${GENESIS_NCU_PROFILER_LEVEL:-detailed}"
    local plan_json

    if [ "${GENESIS_NCU_PROFILE_ENABLED:-0}" -ne 1 ]; then
        return 0
    fi

    echo "Running ${system_name} additional NCU acquisition profiles level=${profiler_level}"
    case "$(genesis_ncu_profile_mode)" in
      manual|configured)
        genesis_run_ncu_profiles "$profiler_level" "$@"
        ;;
      discovery|auto)
        plan_json=$(genesis_generate_ncu_plan "$profiler_level" "$@")
        genesis_run_ncu_plan_profiles "$plan_json" "$profiler_level" "$@"
        ;;
      discovery-only|auto-discovery-only)
        genesis_generate_ncu_plan "$profiler_level" "$@" >/dev/null || return $?
        echo "Genesis ${system_name}: completed NSYS kernel discovery; skipping NCU profile execution."
        ;;
      *)
        echo "Genesis ${system_name}: unsupported BK_GENESIS_NCU_PROFILE_MODE='$(genesis_ncu_profile_mode)'." >&2
        echo "Use manual, discovery, or discovery-only." >&2
        return 1
        ;;
    esac
}

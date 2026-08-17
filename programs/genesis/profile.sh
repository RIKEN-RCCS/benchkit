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
    GENESIS_NCU_PROFILER_TOOL=""

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

    if ! command -v ncu >/dev/null 2>&1; then
        echo "Genesis ${system_name}: ncu profiler requested but ncu is not in PATH." >&2
        echo "Load Nsight Compute with ${module_var}, or set ${profiler_tool_var}=none / GENESIS_PROFILER_TOOL=none / BK_PROFILER=none to run without profiling." >&2
        return 1
    fi

    GENESIS_NCU_PROFILE_ENABLED=1
    GENESIS_NCU_PROFILER_TOOL="$profiler_tool"
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

genesis_register_section_artifact() {
    local section_name="$1"
    local artifact_path="$2"
    local section_key
    local artifact_var

    section_key=$(bk_profile_key "$section_name")
    artifact_var="BK_GENESIS_SECTION_${section_key}_ARTIFACT"
    printf -v "$artifact_var" '%s' "$artifact_path"
    export "$artifact_var"
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

genesis_run_ncu_profile() {
    local profile_name="$1"
    local profile_slug="$2"
    local kernel_regex="$3"
    local launch_skip="$4"
    local launch_count="$5"
    local profiler_level="$6"
    local section_name="$7"
    local discovery_metadata_json="$8"
    shift 8

    local archive_path="${resultsdir}/padata_${profile_slug}.tgz"
    local archive_rel_path="results/padata_${profile_slug}.tgz"
    local metadata_path="${archive_path%.tgz}.metadata.json"
    local metadata_rel_path="${archive_rel_path%.tgz}.metadata.json"
    local raw_dir="ncu_${profile_slug}"
    local profile_log="${resultsdir}/log_${header}_ncu_${profile_slug}.txt"

    bk_run_ncu_acquisition_profile \
        --profile-name "$profile_name" \
        --profile-slug "$profile_slug" \
        --kernel-regex "$kernel_regex" \
        --launch-skip "$launch_skip" \
        --launch-count "$launch_count" \
        --level "$profiler_level" \
        --archive "$archive_path" \
        --archive-rel "$archive_rel_path" \
        --raw-dir "$raw_dir" \
        --log "$profile_log" \
        --section "$section_name" \
        --metadata "$metadata_path" \
        --discovery-json "${discovery_metadata_json:-{}}" \
        -- "$@"

    if [ -n "$section_name" ]; then
        echo "GENESIS NCU profile metadata: ${metadata_rel_path}" >&2
        genesis_register_section_artifact "$section_name" "$archive_rel_path"
    fi
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

        genesis_run_ncu_profile "$profile_name" "$profile_slug" "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" "$(genesis_profile_section_name "$profile_name")" "" "${profile_cmd[@]}"
    done
}

genesis_ncu_profile_mode() {
    printf '%s\n' "${BK_GENESIS_NCU_PROFILE_MODE:-discovery}"
}

genesis_generate_ncu_plan() {
    local profiler_level="$1"
    shift
    local python_bin
    local discovery_csv="${BK_GENESIS_NCU_DISCOVERY_CSV:-${BK_GENESIS_NSYS_KERNEL_SUMMARY_CSV:-}}"
    local discovery_json="${resultsdir}/kernel_discovery.json"
    local plan_json="${resultsdir}/ncu_plan.json"
    local nsys_base="${resultsdir}/nsys_kernel_discovery"
    local nsys_report="${nsys_base}.nsys-rep"
    local nsys_csv="${resultsdir}/nsys_cuda_gpu_kern_sum.csv"
    local nsys_log="${resultsdir}/log_${header}_nsys_discovery.txt"
    local discovery_cmd
    local last_index
    local discovery_input
    local generated_csv
    local nsys_status
    local plan_top_k="${BK_GENESIS_NCU_PLAN_TOP_K:-}"

    python_bin="${PYTHON_BIN:-python3}"
    if ! command -v "$python_bin" >/dev/null 2>&1; then
        echo "GENESIS NCU discovery requires ${python_bin} for plan generation." >&2
        return 1
    fi

    if [ -z "$discovery_csv" ]; then
        if ! command -v nsys >/dev/null 2>&1; then
            echo "GENESIS NCU discovery requires nsys, or set BK_GENESIS_NCU_DISCOVERY_CSV to an existing cuda_gpu_kern_sum CSV." >&2
            return 1
        fi

        discovery_cmd=("$@")
        last_index=$((${#discovery_cmd[@]} - 1))
        if [ "$last_index" -lt 0 ]; then
            echo "GENESIS NCU discovery has no command to run." >&2
            return 1
        fi
        discovery_input=$(genesis_prepare_ncu_input "${discovery_cmd[$last_index]}" "discovery" "discovery" "DISCOVERY")
        discovery_cmd[$last_index]="$discovery_input"

        echo "Running GENESIS NSYS kernel discovery for automatic NCU plan generation level=${profiler_level}" >&2
        set +e
        nsys profile \
            --force-overwrite=true \
            --trace=cuda \
            --sample=none \
            -o "$nsys_base" \
            "${discovery_cmd[@]}" 2>&1 | tee "$nsys_log" >&2
        nsys_status=${PIPESTATUS[0]}
        set -e
        if [ "$nsys_status" -ne 0 ]; then
            echo "GENESIS NSYS kernel discovery failed with status ${nsys_status}" >&2
            return "$nsys_status"
        fi

        if [ ! -f "$nsys_report" ]; then
            echo "GENESIS NSYS report was not created: ${nsys_report}" >&2
            return 1
        fi
        nsys stats --report cuda_gpu_kern_sum --format csv --output "$nsys_csv" "$nsys_report" >/dev/null
        generated_csv=$(find "${resultsdir}" -maxdepth 1 -type f \( -name 'nsys_cuda_gpu_kern_sum*.csv' -o -name 'nsys_cuda_gpu_kern_sum*.csv.*' \) | sort | head -n 1)
        discovery_csv="${generated_csv:-$nsys_csv}"
        echo "GENESIS NSYS CUDA kernel summary CSV: ${discovery_csv}" >&2
        echo "---- GENESIS NSYS CUDA kernel summary begin ----" >&2
        cat "$discovery_csv" >&2
        echo "---- GENESIS NSYS CUDA kernel summary end ----" >&2
    fi

    if [ ! -f "$discovery_csv" ]; then
        echo "GENESIS NCU discovery CSV does not exist: ${discovery_csv}" >&2
        return 1
    fi
    if [ -z "$plan_top_k" ]; then
        case "$(genesis_ncu_profile_mode)" in
          discovery-only|auto-discovery-only)
            plan_top_k=0
            ;;
          *)
            plan_top_k=3
            ;;
        esac
    fi

    "$python_bin" "${SCRIPT_DIR}/scripts/profiling/generate_ncu_plan.py" \
        --nsys-csv "$discovery_csv" \
        --out-discovery "$discovery_json" \
        --out-plan "$plan_json" \
        --top-k "$plan_top_k" \
        --min-total-time-pct "${BK_GENESIS_NCU_PLAN_MIN_TOTAL_TIME_PCT:-0}" \
        --min-instances "${BK_GENESIS_NCU_PLAN_MIN_INSTANCES:-1}" \
        --launch-count "${BK_GENESIS_NCU_PLAN_LAUNCH_COUNT:-${BK_GENESIS_NCU_LAUNCH_COUNT:-10}}" \
        --warmup-fraction "${BK_GENESIS_NCU_PLAN_WARMUP_FRACTION:-0}" \
        --max-launch-skip "${BK_GENESIS_NCU_PLAN_MAX_LAUNCH_SKIP:-1}" \
        --metric-set "${BK_GENESIS_NCU_PLAN_METRIC_SET:-gpu_kernel_estimation}"

    echo "GENESIS kernel discovery JSON: ${discovery_json}" >&2
    echo "---- GENESIS kernel discovery JSON begin ----" >&2
    cat "$discovery_json" >&2
    echo "---- GENESIS kernel discovery JSON end ----" >&2
    echo "GENESIS NCU plan JSON: ${plan_json}" >&2
    echo "---- GENESIS NCU plan JSON begin ----" >&2
    cat "$plan_json" >&2
    echo "---- GENESIS NCU plan JSON end ----" >&2

    printf '%s\n' "$plan_json"
}

genesis_run_ncu_plan_profiles() {
    local plan_json="$1"
    local profiler_level="$2"
    shift 2
    local python_bin
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
    local discovery_metadata_json

    python_bin="${PYTHON_BIN:-python3}"
    mapfile -t profile_rows < <("$python_bin" "${SCRIPT_DIR}/scripts/profiling/iter_ncu_plan_profiles.py" --plan "$plan_json")
    for profile_row in "${profile_rows[@]}"; do
        IFS=$'\t' read -r profile_name section_name kernel_regex launch_skip launch_count kernel_name <<< "$profile_row"
        if [ -z "$profile_name" ] || [ -z "$kernel_regex" ]; then
            continue
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
        genesis_run_ncu_profile "$profile_name" "$profile_slug" "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" "$section_name" "$discovery_metadata_json" "${profile_cmd[@]}"
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
        genesis_generate_ncu_plan "$profiler_level" "$@" >/dev/null
        echo "Genesis ${system_name}: completed NSYS kernel discovery; skipping NCU profile execution."
        ;;
      *)
        echo "Genesis ${system_name}: unsupported BK_GENESIS_NCU_PROFILE_MODE='$(genesis_ncu_profile_mode)'." >&2
        echo "Use manual, discovery, or discovery-only." >&2
        return 1
        ;;
    esac
}

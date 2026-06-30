#!/bin/bash
set -e
set -o pipefail
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
numproc=$(( numproc_node * nodes ))

source "${PWD}/scripts/bk_functions.sh"
source "${PWD}/scripts/estimation/common.sh"
source "${PWD}/programs/genesis/parse_timing.sh"
source "${PWD}/programs/genesis/sections.sh"

genesis_declare_estimation_layout
bk_estimation_apply_declared_defaults

SCRIPT_DIR="${PWD}"
export GENESIS_BENCHKIT_ROOT="$SCRIPT_DIR"
REPO_DIR="genesis_benchmark_input"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="main"
dir_path="npt/genesis2.0beta_3.5fs/apoa1"
header=p8
exp="${BK_GENESIS_EXP:-$header}"
input=${header}.inp
resultsdir=${SCRIPT_DIR}/results
artifactsdir=${SCRIPT_DIR}/artifacts
mkdir -p ${resultsdir}
#tmpdir="/vol0003/share/rccs-sdt/TMP_FugakuNEXT_CICD_LOG/${system}"
#mkdir -p ${tmpdir}
output="${resultsdir}/log_${header}.txt"
stderr="${resultsdir}/log_${header}_err.txt"
binary="spdyn"
inputdir="../../../inputs/apoa1/"

echo "[${REPO_DIR}] Running on system: $system"

if [[ -d "${REPO_DIR}" ]]; then
    if [[ ! -d ${REPO_DIR}/.git ]]; then
        echo "Warning: '${REPO_DIR}' exists but is not a valid git repository. Removing..."
        rm -rf "${REPO_DIR}"
    fi
    if [[ ! -f "${REPO_DIR}/.git/config" ]]; then
        echo "Warning: '${REPO_DIR}' exists but is not a valid git repository. Removing..."
        rm -rf "${REPO_DIR}"
    fi
fi
echo "System=$system"
echo "Nodes=$nodes"
echo "numproc=$numproc"
echo "nthreads=$nthreads"
totalcores=$(( numproc * nthreads ))

if [[ ! -d ${REPO_DIR} ]]; then
    git clone --branch "${BRANCH}" "${REPO_URL}" "${REPO_DIR}"
else
    echo "Reposiotry already exists and looks valid. Skipping clone."
fi


if [[ ! -f "${artifactsdir}/spdyn" ]]; then
    echo "Error: spdyn does not exist."
	exit 1
fi
[[ -f ${artifactsdir}/${binary} ]] && cp ${artifactsdir}/${binary}  "${REPO_DIR}/${dir_path}/${binary}"
if [[ ! -f "${REPO_DIR}/${dir_path}/${binary}" ]]; then
    echo "Error: spdyn is not copied correctly."
	exit 1
fi

cd ${REPO_DIR} || { echo "Failed to enter ${REPO_DIR}"; exit 1; }
cd "$dir_path" || { echo "cd failed to '$dir_path'"; exit 1; }

if [[ ! -f "./${input}" ]]; then
    echo "No inputfile: ${input}"
	exit 1
fi
sed "s#${inputdir}#./#g" ${input} > ${input}.sub

if [[ ! -f "./${binary}" ]]; then
    echo "No binary: ${binary}"
	exit 1
fi

if [[ ! -f ${inputdir}/top_all27_prot_lipid.rtf ]]; then
    echo "No topfile: ${inputdir}/top_all27_prot_lipid.rtf "
	exit 1
fi
cp ${inputdir}/top_all27_prot_lipid.rtf  .

if [[ ! -f ${inputdir}/par_all27_prot_lipid.prm ]]; then
    echo "No topfile: ${inputdir}/par_all27_prot_lipid.prm "
	exit 1
fi
cp ${inputdir}/par_all27_prot_lipid.prm  .

if [[ ! -f ${inputdir}/apoa1.psf ]]; then
    echo "No topfile: ${inputdir}/apoa1.psf "
	exit 1
fi
cp ${inputdir}/apoa1.psf  .

if [[ ! -f ${inputdir}/apoa1.pdb ]]; then
    echo "No topfile: ${inputdir}/apoa1.pdb "
	exit 1
fi
cp ${inputdir}/apoa1.pdb  .

if [[ ! -f ${inputdir}/apoa1.rst ]]; then
    echo "No topfile: ${inputdir}/apoa1.rst "
	exit 1
fi
cp ${inputdir}/apoa1.rst  .

genesis_bool_enabled() {
    case "${1:-}" in
      1|true|TRUE|yes|YES|on|ON)
        return 0
        ;;
    esac
    return 1
}

genesis_ncu_profile_enabled() {
    if [ -n "${BK_GENESIS_NCU_PROFILE:-}" ]; then
        genesis_bool_enabled "$BK_GENESIS_NCU_PROFILE"
        return $?
    fi

    # GH200-class GENESIS runs always keep the unprofiled application run for
    # FOM/section timing, then collect extra NCU windows for GPU-kernel ratios.
    return 0
}

genesis_profile_key() {
    printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g'
}

genesis_profile_slug() {
    local slug
    slug=$(printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_.-]/_/g; s/^_*//; s/_*$//')
    printf '%s\n' "${slug:-profile}"
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

genesis_register_section_artifact() {
    local section_name="$1"
    local artifact_path="$2"
    local section_key
    local artifact_var

    section_key=$(genesis_profile_key "$section_name")
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
    shift 6

    local archive_path="${resultsdir}/padata_${profile_slug}.tgz"
    local archive_rel_path="results/padata_${profile_slug}.tgz"
    local raw_dir="ncu_${profile_slug}"
    local profile_log="${resultsdir}/log_${header}_ncu_${profile_slug}.txt"
    local ncu_args
    local profile_status
    local section_name
    local old_profiler_args="${BK_PROFILER_ARGS:-}"
    local old_profiler_raw_csv="${BK_PROFILER_NCU_RAW_CSV:-}"
    local had_profiler_args=0
    local had_profiler_raw_csv=0

    if [ "${BK_PROFILER_ARGS+x}" ]; then
        had_profiler_args=1
    fi
    if [ "${BK_PROFILER_NCU_RAW_CSV+x}" ]; then
        had_profiler_raw_csv=1
    fi

    ncu_args="--kernel-name-base demangled --kernel-name ${kernel_regex} --launch-skip ${launch_skip} --launch-count ${launch_count}"
    export BK_PROFILER_ARGS="$ncu_args"
    export BK_PROFILER_NCU_RAW_CSV=true

    echo "Running GENESIS NCU profile '${profile_name}' kernel='${kernel_regex}' skip=${launch_skip} count=${launch_count}"
    set +e
    bk_profiler ncu \
        --level "$profiler_level" \
        --archive "$archive_path" \
        --raw-dir "$raw_dir" \
        -- "$@" 2>&1 | tee "$profile_log"
    profile_status=${PIPESTATUS[0]}
    set -e

    if [ "$had_profiler_args" -eq 1 ]; then
        export BK_PROFILER_ARGS="$old_profiler_args"
    else
        unset BK_PROFILER_ARGS
    fi
    if [ "$had_profiler_raw_csv" -eq 1 ]; then
        export BK_PROFILER_NCU_RAW_CSV="$old_profiler_raw_csv"
    else
        unset BK_PROFILER_NCU_RAW_CSV
    fi

    if [ "$profile_status" -ne 0 ]; then
        echo "GENESIS NCU profile '${profile_name}' failed with status ${profile_status}" >&2
        return "$profile_status"
    fi

    section_name=$(genesis_profile_section_name "$profile_name")
    genesis_register_section_artifact "$section_name" "$archive_rel_path"
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

        profile_key=$(genesis_profile_key "$profile_name")
        profile_slug=$(genesis_profile_slug "$profile_name")
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

        genesis_run_ncu_profile "$profile_name" "$profile_slug" "$kernel_regex" "$launch_skip" "$launch_count" "$profiler_level" "${profile_cmd[@]}"
    done
}

# Shared GH200-class run path. The env_prefix pattern mirrors build.sh so each
# site can override modules, MPI launcher, GPU visibility, and profiler policy
# independently while keeping the benchmark invocation identical.
run_genesis_gh200_gpu() {
    local system_name="$1"
    local env_prefix="$2"
    local default_module="$3"
    local module_var="${env_prefix}_MODULE"
    local mpi_cmd_var="${env_prefix}_MPI_CMD"
    local mpi_args_var="${env_prefix}_MPI_ARGS"
    local cuda_visible_devices_var="${env_prefix}_CUDA_VISIBLE_DEVICES"
    local profiler_tool_var="${env_prefix}_PROFILER_TOOL"
    local profiler_level_var="${env_prefix}_PROFILER_LEVEL"

    local module_name="${!module_var:-$default_module}"
    if [ "$module_name" != "none" ] && command -v module >/dev/null 2>&1; then
        read -r -a module_names <<< "$module_name"
        module load "${module_names[@]}"
    fi

    read -r -a mpi_cmd <<< "${!mpi_cmd_var:-mpirun -np ${numproc}}"
    if [ -n "${!mpi_args_var:-}" ]; then
        read -r -a gh200_mpi_args <<< "${!mpi_args_var}"
        mpi_cmd+=("${gh200_mpi_args[@]}")
    fi

    export OMP_NUM_THREADS=${nthreads}
    if [ -n "${!cuda_visible_devices_var:-}" ]; then
        export CUDA_VISIBLE_DEVICES="${!cuda_visible_devices_var}"
    fi

    local genesis_profiler_requested="none"
    local genesis_profiler_explicit=0
    local genesis_profile_enabled=0
    if [ -n "${!profiler_tool_var:-}" ]; then
        genesis_profiler_requested="${!profiler_tool_var}"
        genesis_profiler_explicit=1
    elif [ -n "${GENESIS_PROFILER_TOOL:-}" ]; then
        genesis_profiler_requested="${GENESIS_PROFILER_TOOL}"
        genesis_profiler_explicit=1
    elif genesis_ncu_profile_enabled; then
        genesis_profiler_requested="ncu"
    fi

    if [ "$genesis_profiler_requested" = "none" ]; then
        genesis_profile_enabled=0
    elif genesis_ncu_profile_enabled || [ "$genesis_profiler_requested" != "none" ]; then
        genesis_profile_enabled=1
    fi

    genesis_profiler_tool=$(bk_get_profiler_tool "$genesis_profiler_requested") || return 1
    local genesis_default_profiler_level="single"
    if genesis_ncu_profile_enabled; then
        genesis_default_profiler_level="detailed"
    fi
    genesis_profiler_level="${!profiler_level_var:-${GENESIS_PROFILER_LEVEL:-${genesis_default_profiler_level}}}"
    if [ -n "$genesis_profiler_tool" ]; then
        if [ "$genesis_profiler_tool" = "ncu" ] && ! command -v ncu >/dev/null 2>&1; then
            if [ "$genesis_profiler_explicit" -eq 1 ] || [ "$genesis_profile_enabled" -eq 1 ]; then
                echo "Genesis ${system_name}: ncu profiler requested but ncu is not in PATH." >&2
                echo "Load Nsight Compute with ${module_var}, or set ${profiler_tool_var}=none / GENESIS_PROFILER_TOOL=none to run without profiling." >&2
                return 1
            fi
            genesis_profiler_tool=""
            genesis_profiler_requested="none"
            genesis_profile_enabled=0
        fi
    fi

    echo "Running ${system_name} as Grace-Hopper GPU benchmark run without profiler"
    "${mpi_cmd[@]}" ./${binary} ${input}.sub 2>&1 | tee ${output}

    if [ "$genesis_profile_enabled" -eq 1 ]; then
        if [ "$genesis_profiler_tool" != "ncu" ]; then
            echo "Genesis ${system_name}: only ncu is supported for separate GENESIS GPU profile acquisition." >&2
            return 1
        fi
        echo "Running ${system_name} additional NCU acquisition profiles level=${genesis_profiler_level}"
        genesis_run_ncu_profiles "$genesis_profiler_level" "${mpi_cmd[@]}" ./${binary} ${input}.sub
    fi
}

case "$system" in
  Fugaku)
    mpi_cmd="mpiexec -n ${numproc} -stderr-proc stderr -stdout-proc stdout "
    export PARALLEL=${nthreads}
    export OMP_NUM_THREADS=${nthreads}
	echo "${mpi_cmd} ./${binary} ${input}.sub"
	${mpi_cmd} ./${binary} ${input}.sub
	[[ -f ./stdout.1.0 ]] && cp ./stdout.1.0 ${output}
	[[ -f ./stderr.1.0 ]] && cp ./stderr.1.0 ${stderr}
    ;;
  # FugakuLN retired; previous LN run kept for reference.
  # FugakuLN)
	# . /vol0004/apps/oss/spack/share/spack/setup-env.sh
    # export LD_LIBRARY_PATH=/vol0004/apps/oss/spack-v0.21/opt/spack/linux-rhel8-cascadelake/gcc-13.2.0/openblas-0.3.24-on6q3arf3iucukiz4tfai26noq3kz4a7/lib/:${LD_LIBRARY_PATH}
	# spack load /77gzpid #  gcc@13.2.0 linux-rhel8-skylake_avx512
	# spack load /bnrldb2 # openmpi@4.1.6 linux-rhel8-cascadelake
	# spack load /on6q3ar # openblas@0.3.34 linux-rhel8-cascadelake / gcc@13.2.0
    # mpi_cmd="mpirun -n ${numproc}"
    # export OMP_NUM_THREADS=${nthreads}
	# ${mpi_cmd} ./${binary} ${input}.sub 2>&1 | tee ${output}
    # ;;
  MiyabiG)
    run_genesis_gh200_gpu "$system" GENESIS_MIYABIG none
    ;;
  RC_GH200)
    run_genesis_gh200_gpu "$system" GENESIS_GH200 "system/qc-gh200 nvhpc/25.9"
    ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac

if [[ ! -f "${output}" ]]; then
    echo "No outputfile: ${output}"
	exit 1
fi

fom_val=$(awk -F'=' '/^[[:space:]]*dynamics[[:space:]]*=/ {
			gsub(/^[ \t]+|[ \t]+$/, "", $2);
			print $2;
			exit
			}' ${output})
cd "$SCRIPT_DIR" > /dev/null

if [[ -z "$fom_val" ]]; then
    echo "Warning: FOM value not found in ${output}" >&2
    fom_val="nan"   # or 0.0
fi

{
    bk_emit_result --fom "$fom_val" --exp "$exp" --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads"
    genesis_emit_estimation_data_from_log "$output" "$fom_val"
} >> ${resultsdir}/result
# if information is requierd
#printf "%-10s nodes=%2d numproc=%3d  FOM: %.3f\n" \
#    "$system" "$nodes" "$numproc" "$fom_val" >> ../results/result

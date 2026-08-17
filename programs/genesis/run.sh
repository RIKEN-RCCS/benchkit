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
source "${PWD}/programs/genesis/profile.sh"

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

    genesis_configure_ncu_profile "$system_name" "$profiler_tool_var" "$profiler_level_var" "$module_var" || return 1

    echo "Running ${system_name} as Grace-Hopper GPU benchmark run without profiler"
    "${mpi_cmd[@]}" ./${binary} ${input}.sub 2>&1 | tee ${output}
    genesis_run_configured_ncu_profiles "$system_name" "${mpi_cmd[@]}" ./${binary} ${input}.sub || return 1
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
    bk_emit_result --fom "$fom_val" --fom-unit s --exp "$exp" --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads"
    genesis_emit_estimation_data_from_log "$output" "$fom_val"
} >> ${resultsdir}/result
# if information is requierd
#printf "%-10s nodes=%2d numproc=%3d  FOM: %.3f\n" \
#    "$system" "$nodes" "$numproc" "$fom_val" >> ../results/result

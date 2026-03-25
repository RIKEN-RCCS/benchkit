#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
numproc=$(( numproc_node * nodes ))

source "${PWD}/scripts/bk_functions.sh"

SCRIPT_DIR="${PWD}"
REPO_DIR="genesis-nonbonded-kernels"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="main"
name_list=(Generic Oct Oct_mod1)
dir_list=(Generic Intel Intel_mod1)
resultsdir=${SCRIPT_DIR}/results
artifactsdir=${SCRIPT_DIR}/artifacts

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

if [[ ! -d ${REPO_DIR} ]]; then
    git clone --branch "${BRANCH}" "${REPO_URL}" "${REPO_DIR}"
else
    echo "Reposiotry already exists and looks valid. Skipping clone."
fi

for i in "${!name_list[@]}"; do
    name=${name_list[i]}
    dir_path=${dir_list[i]}
    [[ -f ${artifactsdir}/kernel_${name} ]] && cp ${artifactsdir}/kernel_${name}  "${REPO_DIR}/${dir_path}/kernel"
done

cd ${REPO_DIR} || {
    echo "Failed to enter ${REPO_DIR}"
	exit 1
}

# unpress data file for kernels
cd data
if [[ ! -f data_kernel_Oct && -f data_kernel_Oct.bz2 ]]; then
    bunzip2 data_kernel_Oct.bz2
fi
if [[ ! -f data_kernel_generic && -f data_kernel_generic.bz2 ]]; then
    bunzip2 data_kernel_generic.bz2
fi
cd - > /dev/null

case "$system" in
  Fugaku|FugakuCN|FugakuLN)
    mkdir -p  ${resultsdir}
	#total_fom=0.0
    export PARALLEL=${nthreads}
    export OMP_NUM_THREADS=${nthreads}
	for i in "${!name_list[@]}"; do
	    name=${name_list[i]}
		output="log_${name}.txt"
		dir_path=${dir_list[i]}
		index=$((i + 1))

		echo "Looping over name='$name', dir='$dir_path'"
		cd "$dir_path" || { echo "cd failed to '$dir_path'"; exit 1; }

        ./kernel > ${output}

     	fom_val=$(awk '/time=/{print $2; exit}' ${output})
        cd - > /dev/null

	    #printf "result%d: %.3f\n" "$index" "$fom_val"  >> ${resultsdir}/result
     	#total_fom=$(awk -v a="$total_fom" -v b="$fom_val" 'BEGIN{printf("%.6f", a + b)}')

    bk_emit_result --fom "$fom_val" --exp "$name" --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ${resultsdir}/result
	done

    ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac

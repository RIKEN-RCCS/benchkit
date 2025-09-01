#!/bin/bash
set -e
system="$1"

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

# read programs/genesis-nonbonded-kernels/list.csv

while IFS=, read -r sys mode queue_group nodes numproc_node nthreads elapse; do
  [[ "$sys" == "system" ]] && continue  # skip header
  [[ "$sys" == *"#"* ]] && continue  # skip #
  if [[ "$sys" == "$system" ]]; then
    echo "$sys $system $nodes $numproc_node"
	export elapse nodes queue_group numproc_node nthreads 
    numproc=$(( numproc_node * nodes ))
	export numproc
	break
  fi
done < ${SCRIPT_DIR}/programs/genesis-nonbonded-kernels/list.csv 

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

    printf "Exp: %s " "$name"  >> ${resultsdir}/result
    printf "FOM: %.3f " "$fom_val"  >> ${resultsdir}/result
    printf "node_count: %d " "$nodes"  >> ${resultsdir}/result
    printf "cpus_per_node: %d " "$nodes"  >> ${resultsdir}/result
    printf "cpu_cores: %d " "$totalcores"  >> ${resultsdir}/result
    printf "\n"  >> ${resultsdir}/result
	done

    ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac

#!/bin/bash
set -e
system="$1"

SCRIPT_DIR="${PWD}"
REPO_DIR="genesis_benchmark_input"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="main"
dir_path="npt/genesis2.0beta_3.5fs/apoa1"
header=p8
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
# read programs/genesis/list.csv

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
done < ${SCRIPT_DIR}/programs/genesis/list.csv 

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
  FugakuLN)
	. /vol0004/apps/oss/spack/share/spack/setup-env.sh
    export LD_LIBRARY_PATH=/vol0004/apps/oss/spack-v0.21/opt/spack/linux-rhel8-cascadelake/gcc-13.2.0/openblas-0.3.24-on6q3arf3iucukiz4tfai26noq3kz4a7/lib/:${LD_LIBRARY_PATH}
	spack load /77gzpid #  gcc@13.2.0 linux-rhel8-skylake_avx512
	spack load /bnrldb2 # openmpi@4.1.6 linux-rhel8-cascadelake
	spack load /on6q3ar # openblas@0.3.34 linux-rhel8-cascadelake / gcc@13.2.0
    mpi_cmd="mpirun -n ${numproc}"
    export OMP_NUM_THREADS=${nthreads}
	${mpi_cmd} ./${binary} ${input}.sub 2>&1 | tee ${output}
    ;;
  *)
    echo "Unknown Running system: $system"
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
cd - > /dev/null

if [[ -z "$fom_val" ]]; then
    echo "Warning: FOM value not found in ${output}" >&2
    fom_val="nan"   # or 0.0
fi

printf "FOM: %.3f " "$fom_val"  >> ${resultsdir}/result
printf "node_count: %d " "$nodes"  >> ${resultsdir}/result
printf "cpus_per_node: %d " "$nodes"  >> ${resultsdir}/result
printf "cpu_cores: %d " "$totalcores"  >> ${resultsdir}/result
printf "\n"  >> ${resultsdir}/result
# if information is requierd
#printf "%-10s nodes=%2d numproc=%3d  FOM: %.3f\n" \
#    "$system" "$nodes" "$numproc" "$fom_val" >> ../results/result

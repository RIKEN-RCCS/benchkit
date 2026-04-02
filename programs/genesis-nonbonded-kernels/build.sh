#!/bin/bash
set -e
system="$1"

REPO_DIR="genesis-nonbonded-kernels"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="main"
name_list=(Generic Oct Oct_mod1)
dir_list=(Generic Intel Intel_mod1)

echo "[${REPO_DIR}] Building on system: $system"
mkdir -p artifacts

source scripts/bk_functions.sh
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${BRANCH}"

cd ${REPO_DIR} || {
    echo "Failed to enter ${REPO_DIR}"
	exit 1
}

case "$system" in
    Fugaku)
	comp=frtpx
	dir="normal_${comp}_omp_dir"
	version="--version"
	MARCH=native
	archopt=""
	;;

    FugakuCN)
	comp=frt
	dir="normal_${comp}_omp_dir"
	version="--version"
	archopt=""
	;;

    FugakuLN)
	. /vol0004/apps/oss/spack/share/spack/setup-env.sh
	spack load /77gzpid #  gcc@13.2.0 linux-rhel8-skylake_avx512
	comp=gfortran
	dir="normal_${comp}_omp_dir"
	version="-v"
	archopt="MARCH=native"
	;;
esac

for i in "${!name_list[@]}"; do
    name=${name_list[i]}
	dir_path=${dir_list[i]}
	index=$((i + 1))
	echo "Looping over name='$name', dir='$dir_path'"
	cd "$dir_path" || { echo "cd failed to '$dir_path'"; exit 1; }
    make FC="${comp}" OMP=omp SIMD=dir KIND="${name}" ${archopt}
    cp "$dir/kernel" "../../artifacts/kernel_${name}"
	cd - > /dev/null
done
	
"${comp}" "${version}"

cd ..

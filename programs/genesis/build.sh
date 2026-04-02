#!/bin/bash
set -e
set -x
system="$1"

REPO_DIR="genesis"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="main"

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
	FC=mpifrtpx
	CC=mpifccpx
	CONFIG_ARGS=(--host=Fugaku --enable-mixed)
	version="--version"
	;;

    FugakuLN)
	. /vol0004/apps/oss/spack/share/spack/setup-env.sh
	spack load /77gzpid #  gcc@13.2.0 linux-rhel8-skylake_avx512
	spack load /bnrldb2 # openmpi@4.1.6 linux-rhel8-cascadelake
	spack load /on6q3ar # openblas@0.3.34 linux-rhel8-cascadelake / gcc@13.2.0
	version="-v"
	FC=mpif90
	CC=mpicc
    LAPACK_LIBS="-L/vol0004/apps/oss/spack-v0.21/opt/spack/linux-rhel8-cascadelake/gcc-13.2.0/openblas-0.3.24-on6q3arf3iucukiz4tfai26noq3kz4a7/lib/ -lopenblas"
	CONFIG_ARGS=(--enable-mixed "LAPACK_LIBS=$LAPACK_LIBS")
	;;
esac

echo "FC=$FC"
echo "CC=$CC"
echo "configure args: ${CONFIG_ARGS[@]}"

autoreconf -i
./configure CC="$CC" FC="$FC" "${CONFIG_ARGS[@]}"
make -j > make.log 2>&1 
make install
cp "bin/spdyn" "../artifacts/"
echo "done."

"${FC}" "${version}"

cd ..

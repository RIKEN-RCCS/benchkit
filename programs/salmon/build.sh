#!/bin/bash
set -euo pipefail

system="$1"

REPO_URL="https://github.com/SALMON-TDDFT/SALMON2"
REPO_DIR="SALMON2"
VERSION_TAG="v.2.2.2"
BUILD_DIR="build-benchkit"
ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${VERSION_TAG}"

cd "${REPO_DIR}"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

common_cmake_args=(
  -DUSE_MPI=ON
  -DUSE_SCALAPACK=OFF
  -DUSE_EIGENEXA=OFF
  -DUSE_LIBXC=OFF
  -DCMAKE_BUILD_TYPE=None
  -DCMAKE_VERBOSE_MAKEFILE=ON
)

case "${system}" in
  Fugaku)
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpifrtpx
      -DCMAKE_C_COMPILER=mpifccpx
      -DCMAKE_Fortran_FLAGS="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Ncheck_std=03s"
      -DCMAKE_C_FLAGS="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Xg -std=gnu99"
      -DCMAKE_C_STANDARD_COMPUTED_DEFAULT=Fujitsu
      "-DCMAKE_Fortran_MODDIR_FLAG=-M "
      -DOPENMP_FLAGS="-Kopenmp -Nfjomplib"
      -DLAPACK_VENDOR_FLAGS=-SSL2BLAMP
      -DFortran_PP_FLAGS=-Cpp
    )
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc-hpcx-cuda12/25.7
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpif90
      -DCMAKE_C_COMPILER=mpicc
      -DOPENMP_FLAGS=-Mnoopenmp
      -DUSE_OPENACC=ON
      -DUSE_CUDA=ON
      -DUSE_MPI_DEFAULT=ON
      -DCMAKE_SYSTEM_PROCESSOR=openacc
      -DCMAKE_Fortran_FLAGS="-O3 -Wall -fstrict-aliasing -acc=strict -gpu=cc90,managed,ptxinfo -cudalib=cublas -cuda -Minfo=accel -DUSE_OPENACC -DUSE_CUDA"
      -DCMAKE_C_FLAGS="-O3 -Wall -alias=ansi -acc=strict -gpu=cc90,managed,ptxinfo -cudalib=cublas -cuda -Minfo=accel -DUSE_OPENACC -DUSE_CUDA"
      -DCMAKE_CUDA_ARCHITECTURES=90
      -DCMAKE_CUDA_FLAGS=-arch=sm_90
    )
    ;;
  RC_DGXSP)
    source /etc/profile.d/modules.sh
    module purge
    module load system/ng-dgx nvhpc-hpcx-cuda13/26.3
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpif90
      -DCMAKE_C_COMPILER=mpicc
      -DOPENMP_FLAGS=-Mnoopenmp
      -DUSE_OPENACC=ON
      -DUSE_CUDA=ON
      -DUSE_MPI_DEFAULT=ON
      -DCMAKE_SYSTEM_PROCESSOR=openacc
      -DCMAKE_Fortran_FLAGS="-O3 -Wall -fstrict-aliasing -acc=strict -gpu=cc90,cc100,cc120,managed,ptxinfo -cudalib=cublas -cuda -Minfo=accel -DUSE_OPENACC -DUSE_CUDA"
      -DCMAKE_C_FLAGS="-O3 -Wall -alias=ansi -acc=strict -gpu=cc90,cc100,cc120,managed,ptxinfo -cudalib=cublas -cuda -Minfo=accel -DUSE_OPENACC -DUSE_CUDA"
      -DCMAKE_CUDA_ARCHITECTURES="90;100;120"
      -DCMAKE_CUDA_FLAGS=
    )
    ;;
  RC_GENOA)
    module purge
    module load system/genoa mpi/mpich-x86_64
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpif90
      -DCMAKE_C_COMPILER=mpicc
      -DCMAKE_Fortran_FLAGS="-O3 -ffree-line-length-none -fallow-argument-mismatch"
      -DCMAKE_C_FLAGS=-O3
    )
    ;;
  RC_FX700)
    module purge
    module load system/fx700 FJSVstclanga
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpifrt
      -DCMAKE_C_COMPILER=mpifcc
      -DCMAKE_Fortran_FLAGS="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Ncheck_std=03s"
      -DCMAKE_C_FLAGS="-Kfast -Kocl -Nlst=t -Koptmsg=2 -Xg -std=gnu99"
      -DCMAKE_C_STANDARD_COMPUTED_DEFAULT=Fujitsu
      "-DCMAKE_Fortran_MODDIR_FLAG=-M "
      -DOPENMP_FLAGS="-Kopenmp -Nfjomplib"
      -DLAPACK_VENDOR_FLAGS=-SSL2BLAMP
      -DFortran_PP_FLAGS=-Cpp
    )
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

cmake -S . -B "${BUILD_DIR}" "${cmake_args[@]}"
cmake --build "${BUILD_DIR}" --target salmon --parallel 8

salmon_bin=$(find "${BUILD_DIR}" -type f -name salmon -perm -u+x | head -n 1)
if [[ -z "${salmon_bin}" ]]; then
  salmon_bin=$(find "${BUILD_DIR}" -type f -name salmon | head -n 1)
fi
if [[ -z "${salmon_bin}" || ! -f "${salmon_bin}" ]]; then
  echo "SALMON executable not found under ${BUILD_DIR}" >&2
  exit 1
fi

cp "${salmon_bin}" "${ARTIFACT_DIR}/salmon"

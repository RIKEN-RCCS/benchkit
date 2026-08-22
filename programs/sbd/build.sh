#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh

REPO_URL="https://github.com/r-ccs-cms/sbd.git"
REPO_DIR="sbd"
BUILD_DIR=""
ARTIFACT_DIR="${PWD}/artifacts"

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "main"
cd "${REPO_DIR}"

case "${system}" in
  RIKYU)
    module purge
    module load nvhpc/26.3
    BUILD_DIR="build-rikyu-nvhpc-thrust-rankdist-nccl"
    nccl_root="/shared/software/hpc_sdk/Linux_aarch64/26.3/comm_libs/13.1/nccl"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_GPU_ARCH=cc100 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=ON \
      -DCMAKE_CXX_FLAGS="-I${nccl_root}/include" \
      -DCMAKE_EXE_LINKER_FLAGS="-L${nccl_root}/lib -lnccl"
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  RC_DGXSP)
    source /etc/profile.d/modules.sh
    module purge
    module load system/ng-dgx nvhpc-hpcx-cuda13/26.3
    BUILD_DIR="build-dgxsp-nvhpc-thrust-rankdist"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_GPU_ARCH=cc120 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=OFF
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc-hpcx-cuda13/26.3
    BUILD_DIR="build-gh200-nvhpc-thrust-rankdist"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_GPU_ARCH=cc90 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=OFF
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  RC_FX700)
    module purge
    module load system/fx700 mpi/mpich-aarch64
    BUILD_DIR="build-fx700-gcc-mpich-rankdist"
    fjlib="/opt/FJSVstclanga/cp-1.0.30.01/lib64"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_COMPILER=mpicxx \
      -DCMAKE_CXX_FLAGS="-march=armv8.2-a+sve -msve-vector-bits=512" \
      -DBLAS_LIBRARIES="${fjlib}/libfjlapack.so" \
      -DLAPACK_LIBRARIES="${fjlib}/libfjlapack.so" \
      -DCMAKE_CXX_STANDARD_LIBRARIES="${fjlib}/libfj90i.so ${fjlib}/libfj90f.so ${fjlib}/libfjsrcinfo.so -lelf" \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

binary="${BUILD_DIR}/apps/chemistry_tpb_selected_basis_diagonalization/diag"
if [[ ! -x "${binary}" ]]; then
  echo "SBD executable not found: ${binary}" >&2
  exit 1
fi
cp "${binary}" "${ARTIFACT_DIR}/diag"

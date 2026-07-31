#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh

REPO_URL="https://github.com/r-ccs-cms/sbd.git"
REPO_DIR="sbd"
BUILD_DIR="build-rikyu-nvhpc-thrust-rankdist-nccl"
ARTIFACT_DIR="${PWD}/artifacts"

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "main"
cd "${REPO_DIR}"

case "${system}" in
  RIKYU)
    module purge
    module load nvhpc/26.3
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
    dgx_build_dir="build-dgxsp-nvhpc-thrust-rankdist"
    cmake -S . -B "${dgx_build_dir}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_GPU_ARCH=cc120 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=OFF
    cmake --build "${dgx_build_dir}" --parallel
    BUILD_DIR="${dgx_build_dir}"
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

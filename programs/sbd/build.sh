#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_build.sh

REPO_URL="https://github.com/r-ccs-cms/sbd.git"
REPO_DIR="sbd"
BUILD_DIR=""
ARTIFACT_DIR="${PWD}/artifacts"

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${SBD_BRANCH:-main}" "${SBD_SOURCE_COMMIT:-}"
cd "${REPO_DIR}"

case "${system}" in
  Flow2_Type2)
    [[ "$(uname -m)" == aarch64 ]] || { echo "SBD Type II requires native ARM compilation" >&2; exit 1; }
    module purge
    module load nvhpc/26.5 nv-hpcx/26.5 cmake/4.4.3
    source "$BK_BENCHKIT_ROOT/programs/sbd/flow2_type2_env.sh"
    BUILD_DIR="build-flow2-type2-cpu"
    cmake -S . -B "$BUILD_DIR" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_COMPILER=mpic++ \
      -Dnvpl_DIR="$SBD_FLOW2_NVPL_ROOT/lib/cmake/nvpl" \
      -DBLA_VENDOR=NVPL \
      -DBLA_SIZEOF_INTEGER=4 \
      -DBLA_THREAD=SEQ \
      -DSBD_GPU_BACKEND=none \
      -DSBD_USE_NCCL=OFF \
      -DSBD_USE_CUBLAS=OFF \
      -DSBD_USE_NVTX=OFF \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON
    cmake --build "$BUILD_DIR" --target tpb_diag --parallel 4
    ;;
  Camphor3)
    module switch PrgEnvIntel PrgEnvIntel/2023
    BUILD_DIR="build-camphor3-cpu"
    cmake -S . -B "$BUILD_DIR" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_COMPILER=mpiicpx \
      -DBLA_VENDOR=Intel10_64lp \
      -DSBD_GPU_BACKEND=none \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON
    cmake --build "$BUILD_DIR" --target tpb_diag --parallel 4
    ;;
  Flow2_Type1)
    module purge
    module load oneapi/2026.1.0 impi/2021.18 cmake/4.4.3
    BUILD_DIR="build-flow2-cpu"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_COMPILER=mpiicpx \
      -DBLA_VENDOR=Intel10_64lp \
      -DSBD_GPU_BACKEND=none \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON
    cmake --build "${BUILD_DIR}" --target tpb_diag --parallel 4
    ;;
  RIKYU)
    module purge
    module load nvhpc/26.3
    BUILD_DIR="build-rikyu-nvhpc-thrust-rankdist-nccl"
    nccl_root="/shared/software/hpc_sdk/Linux_aarch64/26.3/comm_libs/13.1/nccl"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_USE_NVTX=ON \
      -DSBD_GPU_ARCH=cc100 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=ON \
      -DCMAKE_CXX_FLAGS="-I${nccl_root}/include" \
      -DCMAKE_EXE_LINKER_FLAGS="-L${nccl_root}/lib -lnccl"
    cmake --build "${BUILD_DIR}" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
    ;;
  RC_DGXSP)
    if ! type module >/dev/null 2>&1; then
      source /etc/profile.d/modules.sh
    fi
    module purge
    module load nvhpc-hpcx/26.3
    BUILD_DIR="build-dgxsp-nvhpc-thrust-rankdist"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_USE_NVTX=ON \
      -DSBD_GPU_ARCH=cc120 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=OFF
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  RC_GH200)
    if ! type module >/dev/null 2>&1; then
      source /etc/profile.d/modules.sh
    fi
    module purge
    module load nvhpc-hpcx/26.9
    BUILD_DIR="build-gh200-nvhpc-thrust-rankdist"
    cmake -S . -B "${BUILD_DIR}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DSBD_GPU_BACKEND=thrust \
      -DSBD_USE_NVTX=ON \
      -DSBD_GPU_ARCH=cc90 \
      -DSBD_THRUST_SAFE_MPI_ALLREDUCE=ON \
      -DSBD_USE_RANK_DISTRIBUTION=ON \
      -DSBD_USE_BLOCK_RANK_DISTRIBUTION=ON \
      -DSBD_REORDER_INDEX_ARRAY=ON \
      -DSBD_USE_NCCL=OFF
    cmake --build "${BUILD_DIR}" --parallel
    ;;
  RC_FX700)
    if ! type module >/dev/null 2>&1; then
      source /etc/profile.d/modules.sh
    fi
    module purge
    module load mpi/mpich-aarch64
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

# Stage benchmark inputs from the source clone into artifacts so run.sh can
# retrieve them on the compute node even when the source tree is absent
# (cross-build mode). See programs/sbd/data/h2o/README.md for provenance.
for input_file in fcidump.txt h2o-1em4-alpha.txt h2o-1em5-alpha.txt \
                  h2o-1em6-alpha.txt h2o-1em7-alpha.txt; do
  cp "data/h2o/${input_file}" "${ARTIFACT_DIR}/${input_file}"
done

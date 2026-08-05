#!/bin/bash
set -euo pipefail

system="$1"

# BenchKit invokes this as `bash programs/petsc-gmres/build.sh <system>`
# from the repo root, not from inside this directory -- $PWD is the repo
# root throughout (matching PETSC_DIR/ARTIFACT_DIR below, and bk_fetch_source's
# own convention). src/GMRES-PETSc.cpp is *this script's own* source, so
# anchor it to the script's location (APP_DIR) instead of assuming a
# caller cwd -- found by actually running this through BenchKit's own
# invocation convention rather than just replicating its commands by hand.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PETSC_REPO="https://gitlab.com/petsc/petsc.git"
PETSC_TAG="v3.25.2"
PETSC_DIR="${PWD}/petsc"
ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${PETSC_REPO}" "petsc" "${PETSC_TAG}"

case "$system" in
  RIKYU)
    module load nvhpc-hpcx/26.3
    export PETSC_ARCH=arch-rikyu
    NVPL=/shared/software/hpc_sdk/Linux_aarch64/26.3/math_libs/nvpl/lib
    (
      cd "${PETSC_DIR}"
      # --with-fc=0: nvhpc-hpcx's Fortran wrapper doesn't support an F2018
      # pointer-initialization feature PETSc's Fortran bindings need; this
      # app is C++ only anyway. --with-cuda=0: this is the CPU-only build
      # (see petsc-benchmarking in RIKEN-RCCS/block1-eeas for why a
      # +cuda-enabled build's PetscInitialize scales ~linearly with rank
      # count from CUDA-library dynamic-linking contention, unrelated to
      # solve performance). Serial NVPL BLAS/LAPACK: this app runs flat
      # MPI, no OpenMP threading.
      ./configure \
        --with-cc=mpicc --with-cxx=mpicxx --with-fc=0 \
        --with-debugging=0 --with-cuda=0 \
        --with-blaslapack-lib="-L${NVPL} -Wl,-rpath,${NVPL} -lnvpl_lapack_lp64_seq -lnvpl_blas_lp64_seq" \
        COPTFLAGS='-O3' CXXOPTFLAGS='-O3'
      make PETSC_DIR="${PETSC_DIR}" PETSC_ARCH="${PETSC_ARCH}" -j8 all
    )
    mpicxx -O3 -I"${PETSC_DIR}/include" -I"${PETSC_DIR}/${PETSC_ARCH}/include" \
      "${APP_DIR}/src/GMRES-PETSc.cpp" -o "${ARTIFACT_DIR}/GMRES-PETSc" \
      -Xlinker -rpath="${PETSC_DIR}/${PETSC_ARCH}/lib" \
      -L"${PETSC_DIR}/${PETSC_ARCH}/lib" -lpetsc
    ;;
  Fugaku)
    # See petsc-build in RIKEN-RCCS/block1-eeas: LLVM cross-compiler
    # (mpiclang++) beats the Fujitsu compiler here, and Fugaku's own
    # Spack-provided PETSc hits the same GAMG square-graph crash as a bare
    # SIGKILL instead of a catchable PETSc error, so we build our own.
    module load lang/tcsds-1.2.43
    module load LLVM/llvmorg-22.1.0
    export PETSC_ARCH=arch-fugaku-llvm
    TCSDS=/opt/FJSVxtclanga/tcsds-latest/lib64
    ELF=/opt/FJSVxos/devkit/aarch64/rfs/usr/lib64/libelf.so
    (
      cd "${PETSC_DIR}"
      # Login nodes are x86, compute nodes are A64FX/aarch64 -- a genuine
      # cross-compile, hence --with-batch. BLAS/LAPACK is Fujitsu's own
      # fjlapacksve (serial), not OpenBLAS -- OpenBLAS pulls in an
      # unresolvable chain of Fortran-runtime symbols on this toolchain
      # (RIKEN's own docs: "use of libraries provided with the Fujitsu
      # compiler with the other compiler environments is not supported",
      # but they document this exact non-Fujitsu-compiler linkage recipe).
      ./configure \
        --with-cc=mpiclang --with-cxx=mpiclang++ --with-fc=0 \
        --with-debugging=0 --with-batch \
        --with-blaslapack-lib="${TCSDS}/libfjlapacksve.so ${TCSDS}/libfj90i.so ${TCSDS}/libfj90f.so ${TCSDS}/libfjsrcinfo.so ${TCSDS}/libfjcrt.so ${ELF}" \
        --PETSC_ARCH="${PETSC_ARCH}"
      make PETSC_DIR="${PETSC_DIR}" PETSC_ARCH="${PETSC_ARCH}" all
    )
    mpiclang++ -O3 -I"${PETSC_DIR}/include" -I"${PETSC_DIR}/${PETSC_ARCH}/include" \
      "${APP_DIR}/src/GMRES-PETSc.cpp" -o "${ARTIFACT_DIR}/GMRES-PETSc" \
      "$(grep '^PETSC_WITH_EXTERNAL_LIB' "${PETSC_DIR}/${PETSC_ARCH}/lib/petsc/conf/petscvariables" | cut -d= -f2-)"
    ;;
  RC_DGXSP)
    # GPU build -- audikw_1 is solved on-GPU here (1 rank/GPU), matching
    # the cross-machine reproduction in RIKEN-RCCS/block1-eeas's
    # petsc-build. -pc_gamg_square_graph 0 (set in run.sh) avoids a
    # cuSPARSE crash on this matrix's connectivity during GAMG's
    # aggressive-coarsening graph-squaring step.
    source /etc/profile.d/modules.sh
    module load system/ng-dgx nvhpc-hpcx
    export PETSC_ARCH=arch-dgxsp-cuda
    CUDA_ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.')
    MATHLIBS=$(dirname "$(command -v nvcc)")/../../math_libs/*/lib64
    (
      cd "${PETSC_DIR}"
      ./configure \
        --with-cc=mpicc --with-cxx=mpicxx --with-fc=0 \
        --with-debugging=0 --with-cuda=1 --with-cuda-arch="${CUDA_ARCH}" \
        LDFLAGS="-L${MATHLIBS} -Wl,-rpath,${MATHLIBS}" \
        COPTFLAGS='-O3' CXXOPTFLAGS='-O3'
      make PETSC_DIR="${PETSC_DIR}" PETSC_ARCH="${PETSC_ARCH}" -j8 all
    )
    mpicxx -O3 -I"${PETSC_DIR}/include" -I"${PETSC_DIR}/${PETSC_ARCH}/include" \
      "${APP_DIR}/src/GMRES-PETSc.cpp" -o "${ARTIFACT_DIR}/GMRES-PETSc" \
      -Xlinker -rpath="${PETSC_DIR}/${PETSC_ARCH}/lib" \
      -L"${PETSC_DIR}/${PETSC_ARCH}/lib" -lpetsc
    ;;
  *)
    echo "Unknown system: $system" >&2
    exit 1
    ;;
esac

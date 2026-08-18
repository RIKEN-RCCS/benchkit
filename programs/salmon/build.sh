#!/bin/bash
set -euo pipefail

system="$1"

REPO_URL="https://github.com/SALMON-TDDFT/SALMON2"
REPO_DIR="SALMON2"
VERSION_TAG="v.2.2.2"
BUILD_DIR="build-benchkit"

# RIKYU pin: v.2.2.2 is over a year stale (2025-06-06) and measured
# GPU-decomposition numbers on this repo were never actually run against it --
# they came from a much newer, hand-patched checkout (~100 commits ahead,
# including PR #1276's OpenACC tuning). Rather than let RIKYU silently build
# something nobody has benchmarked, pin it to FugakuNEXT-v1 on
# william-dawson/SALMON2 (also open as SALMON-TDDFT/SALMON2#1276) --
# develop-2.0.0@9b93a8c4 (2026-08-16) plus four commits, one per concern:
#   1. PR #1276's stencil/current/pseudo-pt OpenACC tuning (batched cuBLAS
#      GEMM for pseudo-pt, not the old USE_CUDA hand-written kernels --
#      see below)
#   2. the nvhpc-openacc-gemm.cmake platform file that wires it up
#   3. the nvhpc/26.5 Ewald-reduction compiler-bug workaround
#   4. a fix for a real, 100%-reproducible 2+ node hang on native
#      nvhpc/26.5 (forces CUDA context creation before MPI_Init_thread --
#      see below, and salmon-gpu-optimization-ideas' Open item 5 in
#      subwg2-benchmarks for the full root-cause trail)
# See .claude/skills/salmon-gpu-optimization-ideas and salmon-build in
# subwg2-benchmarks for how each piece was measured/root-caused.
if [[ "${system}" == "RIKYU" ]]; then
  REPO_URL="https://github.com/william-dawson/SALMON2"
  VERSION_TAG="FugakuNEXT-v1"
fi
ARTIFACT_DIR="${PWD}/artifacts"
RESULTS_DIR="${PWD}/results"
BUILD_LOG_DIR="${RESULTS_DIR}/salmon_build_logs"
AOCL_ROOT_DEFAULT="/lvs0/rccs-nghpcadu/nakamura/aocl/install"
FJMPI_PATCH="${PWD}/programs/salmon/patches/fjmpi-topology-guard.patch"
EWALD_265_PATCH="${PWD}/programs/salmon/patches/nvhpc265-ewald-reduction.patch"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
mkdir -p "${BUILD_LOG_DIR}"
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${VERSION_TAG}"

cd "${REPO_DIR}"
if git apply --check "${FJMPI_PATCH}"; then
  git apply "${FJMPI_PATCH}"
elif git apply --reverse --check "${FJMPI_PATCH}" >/dev/null 2>&1; then
  echo "SALMON Fujitsu MPI topology patch is already applied"
else
  echo "SALMON Fujitsu MPI topology patch does not apply to ${VERSION_TAG}" >&2
  exit 1
fi

apply_ewald_265_patch() {
  # Works around a silent nvfortran 26.5 OpenACC reduction-codegen bug that
  # gives a wrong (but plausible) total energy -- see the patch file itself
  # and .claude/skills/salmon-build in subwg2-benchmarks for the full trail.
  # Safe to apply on every OpenACC/GPU build regardless of nvhpc version:
  # the fix gates itself on __NVCOMPILER_MAJOR__/__NVCOMPILER_MINOR__ at
  # compile time, so it's a no-op on unaffected compilers (<26.5).
  if git apply --check "${EWALD_265_PATCH}"; then
    git apply "${EWALD_265_PATCH}"
  elif git apply --reverse --check "${EWALD_265_PATCH}" >/dev/null 2>&1; then
    echo "SALMON nvhpc/26.5 Ewald-reduction patch is already applied"
  else
    echo "SALMON nvhpc/26.5 Ewald-reduction patch does not apply to ${VERSION_TAG}" >&2
    exit 1
  fi
}

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

common_cmake_args=(
  -DUSE_MPI=ON
  -DUSE_SCALAPACK=OFF
  -DUSE_EIGENEXA=OFF
  -DUSE_LIBXC=OFF
  -DCMAKE_BUILD_TYPE=None
  -DCMAKE_VERBOSE_MAKEFILE=OFF
)

print_log_summary() {
  local logfile="$1"

  grep -E "Build Netlib LAPACK|Set vendor-specific LAPACK|Found (BLAS|LAPACK|OpenMP|MPI)|Downloading|Built target salmon|Linking Fortran executable|error:|ERROR" "${logfile}" \
    | tail -n 80 || true
}

run_logged() {
  local label="$1"
  local logfile="$2"
  shift 2

  echo "${label}; full log: ${logfile}"
  if "$@" > "${logfile}" 2>&1; then
    print_log_summary "${logfile}"
    return 0
  fi

  echo "${label} failed; full log: ${logfile}" >&2
  echo "---- ${logfile} tail ----" >&2
  tail -n 160 "${logfile}" >&2 || true
  exit 1
}

case "${system}" in
  Fugaku)
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpifrtpx
      -DCMAKE_C_COMPILER=mpifccpx
      -DCMAKE_Fortran_FLAGS="-Kfast -Kocl -Ncheck_std=03s -Nalloc_assign"
      -DCMAKE_C_FLAGS="-Kfast -Kocl -Xg -std=gnu99"
      -DCMAKE_C_STANDARD_COMPUTED_DEFAULT=Fujitsu
      "-DCMAKE_Fortran_MODDIR_FLAG=-M "
      -DOPENMP_FLAGS="-Kopenmp -Nfjomplib"
      -DLAPACK_VENDOR_FLAGS=-SSL2BLAMP
      -DFortran_PP_FLAGS=-Cpp
      -DUSE_FJMPI=ON
    )
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc-hpcx-cuda12/25.7
    apply_ewald_265_patch
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
    apply_ewald_265_patch
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
    module load system/genoa mpi/openmpi-x86_64
    aocl_root="${BK_SALMON_AOCL_ROOT:-${AOCL_ROOT_DEFAULT}}"
    aocl_blis_lib="${aocl_root}/amd-blis/lib/LP64"
    aocl_flame_lib="${aocl_root}/amd-libflame/lib/LP64"
    aocl_utils_lib=""
    aocl_utils_so="$(find "${aocl_root}" -type f -name libaoclutils.so -print -quit 2>/dev/null || true)"
    aocl_cpuid_so="$(find "${aocl_root}" -type f -name libau_cpuid.so -print -quit 2>/dev/null || true)"
    if [[ -n "${aocl_utils_so}" ]]; then
      aocl_utils_lib="$(dirname "${aocl_utils_so}")"
    fi
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpif90
      -DCMAKE_C_COMPILER=mpicc
      -DCMAKE_Fortran_FLAGS="-O3 -ffree-line-length-none -fallow-argument-mismatch"
      -DCMAKE_C_FLAGS=-O3
    )
    if [[ -f "${aocl_blis_lib}/libblis-mt.so" && -f "${aocl_flame_lib}/libflame.so" && -n "${aocl_utils_so}" && -n "${aocl_cpuid_so}" ]]; then
      export LD_LIBRARY_PATH="${aocl_utils_lib}:${aocl_flame_lib}:${aocl_blis_lib}:${LD_LIBRARY_PATH:-}"
      cmake_args+=("-DLAPACK_VENDOR_FLAGS=${aocl_flame_lib}/libflame.so ${aocl_blis_lib}/libblis-mt.so ${aocl_utils_so} ${aocl_cpuid_so}")
    elif command -v pkg-config >/dev/null 2>&1 && pkg-config --exists openblas; then
      cmake_args+=("-DLAPACK_VENDOR_FLAGS=$(pkg-config --libs openblas)")
    elif ldconfig -p 2>/dev/null | grep -q 'libopenblas\.so'; then
      cmake_args+=(-DLAPACK_VENDOR_FLAGS=-lopenblas)
    else
      echo "System OpenBLAS/LAPACK not found; SALMON may build bundled Netlib LAPACK." >&2
    fi
    ;;
  # RC_FX700)
  #   FX700 currently fails during GS initialization even with the Fujitsu
  #   topology guard patch applied. Keep this route disabled until verified.
  #   module purge
  #   module load system/fx700 FJSVstclanga
  #   export SLURM_MPI_TYPE=pmix
  #   cmake_args=(
  #     "${common_cmake_args[@]}"
  #     -DCMAKE_Fortran_COMPILER=mpifrt
  #     -DCMAKE_C_COMPILER=mpifcc
  #     -DCMAKE_Fortran_FLAGS="-Kfast -Kocl -Ncheck_std=03s -Nalloc_assign"
  #     -DCMAKE_C_FLAGS="-Kfast -Kocl -Xg -std=gnu99"
  #     -DCMAKE_C_STANDARD_COMPUTED_DEFAULT=Fujitsu
  #     "-DCMAKE_Fortran_MODDIR_FLAG=-M "
  #     -DOPENMP_FLAGS="-Kopenmp -Nfjomplib"
  #     -DLAPACK_VENDOR_FLAGS=-SSL2BLAMP
  #     -DFortran_PP_FLAGS=-Cpp
  #     -DUSE_FJMPI=OFF
  #   )
  #   ;;
  RIKYU)
    module purge
    module load nvhpc/26.5
    apply_ewald_265_patch
    cmake_args=(
      "${common_cmake_args[@]}"
      -DCMAKE_Fortran_COMPILER=mpif90
      -DCMAKE_C_COMPILER=mpicc
      -DOPENMP_FLAGS=-Mnoopenmp
      -DUSE_OPENACC=ON
      -DUSE_MPI_DEFAULT=ON
      -DCMAKE_SYSTEM_PROCESSOR=openacc
      -DCMAKE_Fortran_FLAGS="-O3 -Wall -fstrict-aliasing -acc=strict -gpu=cc100,managed,ptxinfo -cudalib=cublas,cusolver -cuda -Minfo=accel -DUSE_OPENACC -DUSE_GEMM"
      -DCMAKE_C_FLAGS="-O3 -Wall -alias=ansi -acc=strict -gpu=cc100,managed,ptxinfo -cudalib=cublas,cusolver -cuda -Minfo=accel -DUSE_OPENACC -DUSE_GEMM"
      # nvhpc/26.5, native MPI3 ON (no FORTRAN_COMPILER_HAS_MPI_VERSION3
      # override needed): this used to hang 2+ node orbital decomposition
      # -- died right after init_ps with a UCC inter-node protocol error
      # (`cannot find remote protocol for: UCC_UCP_CONTEXT inter-node
      # cfg#N | tag_send from cuda-managed/GPU0`), then spun at ~99% CPU
      # producing zero further output -- but that's now fixed at the
      # source (FugakuNEXT-v1's 4th commit: acc_init(acc_device_nvidia)
      # before MPI_Init_thread, so UCC's CUDA-aware protocol probe during
      # MPI_Init's team bootstrap doesn't run with no CUDA context and
      # cache a broken config). Root-caused via a live gdb backtrace on
      # the hung process and compute-sanitizer on the real binary -- see
      # subwg2-benchmarks' salmon-gpu-optimization-ideas skill, Open item
      # 5, for the full trail, and don't reintroduce the old
      # nvhpc/26.3 + FORTRAN_COMPILER_HAS_MPI_VERSION3=OFF workaround this
      # replaces: native 26.5 MPI3 is faster and this pin is what's
      # actually been verified end-to-end (orbital 1-8 nodes, domain 1-2
      # nodes, all bit-exact, on the real build.sh + real artifact).
      #
      # NOT -DUSE_CUDA -- that flag controls a completely different, OLDER
      # optimization path (src/common/{zpseudo,stencil_current}.cu, hand-
      # written CUDA kernels) that this pinned source (see VERSION_TAG
      # above) replaces with PR #1276's tuned pure-OpenACC kernels instead:
      # a batched cuBLAS GEMM rewrite of pseudo-pt (-DUSE_GEMM, needs
      # cusolver linked in) and an inlined OpenACC current-density kernel.
      # That's where the real speedup comes from, not USE_CUDA -- measured
      # data only ever showed the OLD CUDA kernels net *losing* time
      # (pseudo-pt 3.1-3.5x slower under USE_CUDA than plain OpenACC; the
      # 1.4-3x win on current-density wasn't enough to make up for it).
      # USE_CUDA also has a real, deterministic bug independent of any of
      # this: stencil_current.cu's host wrapper sizes its device idx/idy/idz
      # buffers by each rank's LOCAL grid extent but indexes them with the
      # RAW/global grid coordinate, which only happens to fit when a rank's
      # is()=1 on that axis (single GPU, or pure orbital decomposition,
      # where every rank owns the full box). Any real-space (nproc_rgrid>1)
      # decomposition puts a non-first rank at is()>1 on the split axis and
      # overruns the buffer -- reproduced as a deterministic Accelerator
      # Fatal Error / CUDA_ERROR_ILLEGAL_ADDRESS in calc_current
      # (density_matrix.f90) on every axis and Po x Pg combination tried.
      # See subwg2-benchmarks' salmon-gpu-optimization-ideas skill (Open
      # item 5) and salmon-build skill for the full trail on both points.
    )
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

run_logged "Configuring SALMON" "${BUILD_LOG_DIR}/${system}_configure.log" \
  cmake -Wno-dev -S . -B "${BUILD_DIR}" "${cmake_args[@]}"
run_logged "Building SALMON" "${BUILD_LOG_DIR}/${system}_build.log" \
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

#!/bin/bash
set -euo pipefail

system="$1"

REPO_URL="https://github.com/SALMON-TDDFT/SALMON2"
REPO_DIR="SALMON2"
VERSION_TAG="v.2.2.2"
BUILD_DIR="build-benchkit"
ARTIFACT_DIR="${PWD}/artifacts"
RESULTS_DIR="${PWD}/results"
BUILD_LOG_DIR="${RESULTS_DIR}/salmon_build_logs"
AOCL_ROOT_DEFAULT="/lvs0/rccs-nghpcadu/nakamura/aocl/install"
FJMPI_PATCH="${PWD}/programs/salmon/patches/fjmpi-topology-guard.patch"

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

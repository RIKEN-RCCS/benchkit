#!/bin/bash
set -e
set -x
system="$1"

REPO_DIR="genesis"
REPO_URL="${GENESIS_REPO_URL:-https://github.com/genesis-release-r-ccs/${REPO_DIR}.git}"
BRANCH="${GENESIS_BRANCH:-main}"

echo "[${REPO_DIR}] Building on system: $system"
mkdir -p artifacts

source scripts/bk_functions.sh
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${BRANCH}"

cd ${REPO_DIR} || {
    echo "Failed to enter ${REPO_DIR}"
	exit 1
}

append_env_flags() {
    local var_name="$1"
    local new_flags="$2"
    local current_flags="${!var_name:-}"

    if [ -n "$new_flags" ]; then
        if [ -n "$current_flags" ]; then
            export "${var_name}=${current_flags} ${new_flags}"
        else
            export "${var_name}=${new_flags}"
        fi
    fi
}

detect_cuda_path() {
    local nvcc_path=""
    local nvcc_prefix=""
    local nvhpc_root=""
    local cuda_candidate=""

    if [ -n "${CUDA_HOME:-}" ]; then
        printf '%s\n' "$CUDA_HOME"
        return 0
    fi
    if [ -n "${CUDA_PATH:-}" ]; then
        printf '%s\n' "$CUDA_PATH"
        return 0
    fi
    if ! nvcc_path=$(command -v nvcc 2>/dev/null); then
        return 1
    fi

    nvcc_prefix=$(cd "$(dirname "$(dirname "$nvcc_path")")" && pwd)
    nvhpc_root=$(cd "$(dirname "$nvcc_prefix")" && pwd)
    for cuda_candidate in "${nvhpc_root}"/cuda/* "${nvhpc_root}"/cuda; do
        if [ -f "${cuda_candidate}/lib64/libcudart.so" ] || [ -f "${cuda_candidate}/targets/sbsa-linux/lib/libcudart.so" ]; then
            printf '%s\n' "$cuda_candidate"
            return 0
        fi
    done

    if [ -d "${nvcc_prefix}/include" ]; then
        printf '%s\n' "$nvcc_prefix"
        return 0
    fi

    return 1
}

configure_cuda_environment() {
    local cuda_prefix="$1"
    local cuda_arch="$2"
    local incflags=""
    local ldflags=""
    local inc_dir=""
    local lib_dir=""
    local cudart_lib=""

    [ -n "$cuda_prefix" ] || return 0

    export CUDA_HOME="$cuda_prefix"
    export CUDA_PATH="$cuda_prefix"

    for inc_dir in \
        "${cuda_prefix}/include" \
        "${cuda_prefix}/targets/sbsa-linux/include" \
        "${cuda_prefix}/targets/sbsa-linux/include/nvtx3"; do
        if [ -d "$inc_dir" ]; then
            incflags="${incflags:+${incflags} }-I${inc_dir}"
        fi
    done

    for lib_dir in \
        "${cuda_prefix}/targets/sbsa-linux/lib" \
        "${cuda_prefix}/lib64"; do
        if [ -d "$lib_dir" ]; then
            ldflags="${ldflags:+${ldflags} }-L${lib_dir}"
        fi
    done

    for cudart_lib in \
        "${cuda_prefix}/targets/sbsa-linux/lib/libcudart.so" \
        "${cuda_prefix}/lib64/libcudart.so"; do
        if [ -f "$cudart_lib" ]; then
            export GENESIS_CUDART_LIB="$cudart_lib"
            break
        fi
    done

    append_env_flags CPPFLAGS "$incflags"
    append_env_flags NVCCFLAG "$incflags"
    append_env_flags LDFLAGS "$ldflags"

    if [ "$cuda_arch" = "90" ] || [ "$cuda_arch" = "sm_90" ]; then
        append_env_flags NVCCFLAG '--generate-code=arch=compute_90,code="sm_90,compute_90"'
    fi
}

apply_genesis_nvtx_include_patch() {
    local target="src/spdyn/gpu_sp_energy.cu"

    if [ -f "$target" ] && grep -q 'nvToolsExt.h' "$target" && ! grep -q 'nvtx3/nvToolsExt.h' "$target"; then
        sed -i -e 's|nvToolsExt.h|nvtx3/nvToolsExt.h|g' "$target"
    fi
}

apply_genesis_nvfortran_configure_patch() {
    if [ ! -f configure.ac ] || grep -q 'x"${vtok}" = x"nvfortran"' configure.ac; then
        return 0
    fi

    perl -0pi -e 's/(elif test x"\$\{vtok\}" = x"pgfortran"; then\s+FC_ACT="pgf90"\s+break)/elif test x"\${vtok}" = x"nvfortran"; then\nFC_ACT="pgf90"\nbreak\n\1/' configure.ac
    if ! grep -q 'x"${vtok}" = x"nvfortran"' configure.ac; then
        echo "Failed to patch configure.ac for nvfortran detection" >&2
        exit 1
    fi
}

apply_genesis_nvhpc_configure_flags_patch() {
    if [ ! -f configure.ac ]; then
        return 0
    fi

    GENESIS_NVHPC_GPU_FLAGS="${GENESIS_NVHPC_GPU_FLAGS:--cuda -gpu=cc90}" \
    perl -0pi -e '
        my $cudart_lib = $ENV{"GENESIS_CUDART_LIB"};
        my $gpu_flags = $ENV{"GENESIS_NVHPC_GPU_FLAGS"};
        if ($cudart_lib) {
            s/-L\$\{cuda_lib_path\} -lcudart/$cudart_lib/g;
        }
        s/-Mcuda/$gpu_flags/g;
        s/[[:space:]]+-Msmartalloc=huge//g;
        s/[[:space:]]+-Mipa=fast,inline//g;
        s/[[:space:]]+-fastsse//g;
        s/[[:space:]]+-pc 64//g;
        s/[[:space:]]+-mcmodel=medium//g;
        s/\n[[:space:]]*AC_DEFINE\(PGICUDA, 1, \[defined if pgi and cuda are used\.\]\)//g;
        s/\n[[:space:]]*DEFINED_VARIABLES\+=" -DPGICUDA"//g;
    ' configure.ac
    if grep -q 'PGICUDA' configure.ac; then
        echo "Failed to patch configure.ac for NVHPC PGICUDA handling" >&2
        exit 1
    fi
}

bootstrap_genesis() {
    if [ -x ./bootstrap ]; then
        bash ./bootstrap
    else
        autoreconf -i
    fi
}

configure_genesis_gh200_gpu() {
    local system_name="$1"
    local env_prefix="$2"
    local default_module="$3"
    local module_var="${env_prefix}_MODULE"
    local fc_var="${env_prefix}_FC"
    local cc_var="${env_prefix}_CC"
    local cxx_var="${env_prefix}_CXX"
    local f77_var="${env_prefix}_F77"
    local config_args_var="${env_prefix}_CONFIG_ARGS"
    local gpu_arch_var="${env_prefix}_GPU_ARCH"
    local cuda_path_var="${env_prefix}_CUDA_PATH"
    local lapack_libs_var="${env_prefix}_LAPACK_LIBS"
    local ppflags_var="${env_prefix}_PPFLAGS"
    local default_ppflags="-traditional-cpp -traditional -D_SINGLE -DHAVE_MPI_GENESIS -DOMP -DFFTE -DUSE_GPU"
    local gpu_arch_value="${!gpu_arch_var:-sm_90}"
    local cuda_arch_number="${gpu_arch_value#sm_}"
    local gpu_arch="sm_${cuda_arch_number}"
    local cuda_prefix=""

    local module_name="${!module_var:-$default_module}"
    if [ "$module_name" != "none" ] && command -v module >/dev/null 2>&1; then
        read -r -a module_names <<< "$module_name"
        module load "${module_names[@]}"
    fi

    version="--version"
    FC="${!fc_var:-mpif90}"
    CC="${!cc_var:-mpicc}"
    CXX="${!cxx_var:-mpicxx}"
    F77="${!f77_var:-mpif77}"

    cuda_prefix="${!cuda_path_var:-}"
    if [ -z "$cuda_prefix" ]; then
        cuda_prefix=$(detect_cuda_path || true)
    fi
    configure_cuda_environment "$cuda_prefix" "$cuda_arch_number"
    export GENESIS_NVHPC_GPU_FLAGS="${GENESIS_NVHPC_GPU_FLAGS:--cuda -gpu=cc${cuda_arch_number}}"

    if [ -n "${!config_args_var:-}" ]; then
        read -r -a CONFIG_ARGS <<< "${!config_args_var}"
    else
        CONFIG_ARGS=(--enable-single --with-simd=auto --enable-mpi --without-lapack --enable-gpu --enable-openmp "--with-gpuarch=${gpu_arch}")
        if [ -n "$cuda_prefix" ]; then
            CONFIG_ARGS+=("--with-cuda=${cuda_prefix}")
        fi
        if [ -n "${!lapack_libs_var:-}" ]; then
            export LAPACK_LIBS="${!lapack_libs_var}"
            CONFIG_ARGS=("${CONFIG_ARGS[@]/--without-lapack/--with-lapack}")
            CONFIG_ARGS+=("LAPACK_LIBS=${!lapack_libs_var}")
        fi
    fi

    append_env_flags PPFLAGS "${!ppflags_var:-$default_ppflags}"

    apply_genesis_nvtx_include_patch
    apply_genesis_nvfortran_configure_patch
    apply_genesis_nvhpc_configure_flags_patch
    echo "Configured ${system_name} as Grace-Hopper GPU build"
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

    MiyabiG)
    configure_genesis_gh200_gpu "$system" GENESIS_MIYABIG none
	;;

    RC_GH200)
    configure_genesis_gh200_gpu "$system" GENESIS_GH200 "system/qc-gh200 nvhpc/25.9"
	;;

    *)
    echo "Unknown system: $system"
    exit 1
    ;;
esac

echo "FC=$FC"
echo "CC=$CC"
echo "CXX=${CXX:-}"
echo "F77=${F77:-}"
echo "configure args: ${CONFIG_ARGS[@]}"

bootstrap_genesis
configure_env=(CC="$CC" FC="$FC")
if [ -n "${CXX:-}" ]; then
    configure_env+=(CXX="$CXX")
fi
if [ -n "${F77:-}" ]; then
    configure_env+=(F77="$F77")
fi
./configure "${configure_env[@]}" "${CONFIG_ARGS[@]}"
apply_genesis_nvtx_include_patch
if ! make -j > make.log 2>&1; then
    echo "make failed. Error-like lines from make.log:" >&2
    grep -n -i -E 'error|fatal|undefined reference|no such file|cannot|failed|unknown switch|unsupported|stop\.' make.log | tail -n 200 >&2 || true
    echo "make failed. Last 1000 lines of make.log:" >&2
    tail -n 1000 make.log >&2 || true
    exit 1
fi
make install
cp "bin/spdyn" "../artifacts/"
echo "done."

"${FC}" "${version}"

cd ..

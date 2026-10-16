#!/bin/bash
# Source after loading the Flow2 Type II NVHPC/HPC-X modules.
sbd_flow2_type2_environment() {
    local mpi_prefix stack_prefix library_paths="" lib_dir
    if [[ -z "${OMPI_HOME:-}" || -z "${NVHPC_ROOT:-}" ]]; then
        echo "SBD Type II requires the NVHPC and HPC-X modules" >&2
        return 1
    fi
    mpi_prefix=$(cd "$OMPI_HOME" && pwd -P) || return 1
    stack_prefix=${mpi_prefix%/*}
    export OMPI_HOME="$mpi_prefix"
    export SBD_FLOW2_NVPL_ROOT="$NVHPC_ROOT/math_libs/nvpl"
    for lib_dir in "$mpi_prefix/lib/libmpi.so" "$mpi_prefix/lib/libopen-pal.so" \
        "$mpi_prefix/lib/libpmix.so" \
        "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_blas_lp64_seq.so" \
        "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_lapack_lp64_seq.so" \
        "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_blas_core.so" \
        "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_lapack_core.so" \
        "$SBD_FLOW2_NVPL_ROOT/lib/cmake/nvpl/nvpl-config.cmake"; do
        [[ -f "$lib_dir" ]] || { echo "SBD Type II dependency missing: $lib_dir" >&2; return 1; }
    done
    for lib_dir in "$SBD_FLOW2_NVPL_ROOT/lib" "$mpi_prefix/lib" \
        "$stack_prefix/ucx/lib" "$stack_prefix/ucc/lib" \
        "$stack_prefix/hcoll/lib" "$stack_prefix/sharp/lib"; do
        [[ -d "$lib_dir" ]] || continue
        library_paths+="${library_paths:+:}$lib_dir"
    done
    export LD_LIBRARY_PATH="$library_paths${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export PATH="$mpi_prefix/bin:$PATH"
    export OPAL_PREFIX="$mpi_prefix" PMIX_PREFIX="$mpi_prefix" PRTE_PREFIX="$mpi_prefix"
    # Use the existing MPI C ABI with GNU C++17/OpenMP and sequential NVPL.
    export OMPI_CXX=g++ CXX=mpic++
}
sbd_flow2_type2_environment

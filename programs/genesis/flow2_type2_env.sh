#!/bin/bash
# Source after loading the Flow2 Type II NVHPC and HPC-X modules.
# Keep the MPI libraries and their PMIx dependency from the same installation.
genesis_flow2_type2_mpi_env() {
    local mpi_prefix stack_prefix lib_dir library_paths=""
    if [[ -z "${OMPI_HOME:-}" || ! -d "$OMPI_HOME/lib" ]]; then
        echo "GENESIS Type II: HPC-X module must provide OMPI_HOME/lib" >&2
        return 1
    fi
    mpi_prefix=$(cd "$OMPI_HOME" && pwd -P) || return 1
    stack_prefix=${mpi_prefix%/*}
    for lib_dir in "$mpi_prefix/lib/libmpi.so" "$mpi_prefix/lib/libopen-pal.so" "$mpi_prefix/lib/libpmix.so"; do
        if [[ ! -f "$lib_dir" ]]; then
            echo "GENESIS Type II: missing HPC-X library: $lib_dir" >&2
            return 1
        fi
    done
    # The site module leaves the library path unchanged. In particular an
    # older system PMIx with the same SONAME must not override HPC-X PMIx.
    for lib_dir in "$mpi_prefix/lib" "$stack_prefix/ucx/lib" "$stack_prefix/ucc/lib" "$stack_prefix/hcoll/lib" "$stack_prefix/sharp/lib"; do
        [[ -d "$lib_dir" ]] || continue
        library_paths+="${library_paths:+:}$lib_dir"
    done
    export LD_LIBRARY_PATH="$library_paths${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export PATH="$mpi_prefix/bin:$PATH"
    export OPAL_PREFIX="$mpi_prefix" PMIX_PREFIX="$mpi_prefix" PRTE_PREFIX="$mpi_prefix"
}
genesis_flow2_type2_mpi_env
